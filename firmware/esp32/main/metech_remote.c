#include "metech_remote.h"
#include <stdio.h>
#include <string.h>
#include <time.h>
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "mqtt_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "mbedtls/md.h"
#include "nvs.h"

#define REMOTE_NAMESPACE "metech_remote"
#define REMOTE_ENDPOINT_MAX 160
#define REMOTE_ID_MAX 32
#define REMOTE_SECRET_MAX 65
static SemaphoreHandle_t remote_lock;
static metech_remote_status_t remote_status = {.state=METECH_REMOTE_DISABLED};
static char endpoint[REMOTE_ENDPOINT_MAX], device_id[REMOTE_ID_MAX], secret[REMOTE_SECRET_MAX], transport[8];
static esp_mqtt_client_handle_t mqtt_client;

static void remote_set(metech_remote_state_t state, const char *error, unsigned retry_s) { if (xSemaphoreTake(remote_lock, pdMS_TO_TICKS(50)) != pdTRUE) return; remote_status.state=state; remote_status.retry_after_s=retry_s ? (unsigned)(esp_timer_get_time()/1000000ULL)+retry_s : 0; snprintf(remote_status.error,sizeof(remote_status.error),"%s",error?error:""); xSemaphoreGive(remote_lock); }
const char *metech_remote_transport_name(metech_remote_transport_t t) { return t==METECH_REMOTE_MQTT?"mqtt":"https"; }
const char *metech_remote_state_name(metech_remote_state_t s) { return s==METECH_REMOTE_WAIT_CLOCK?"wait_clock":s==METECH_REMOTE_CONNECTING?"connecting":s==METECH_REMOTE_READY?"ready":s==METECH_REMOTE_COOLDOWN?"cooldown":"disabled"; }
void metech_remote_status(metech_remote_status_t *out) { if(xSemaphoreTake(remote_lock,pdMS_TO_TICKS(50))==pdTRUE){*out=remote_status;xSemaphoreGive(remote_lock);} }
static bool load_config(void) { nvs_handle_t n; size_t z; uint8_t enabled=0; if(nvs_open(REMOTE_NAMESPACE,NVS_READONLY,&n)!=ESP_OK)return false; nvs_get_u8(n,"enabled",&enabled); z=sizeof(endpoint); bool ok=enabled&&nvs_get_str(n,"endpoint",endpoint,&z)==ESP_OK; z=sizeof(device_id); ok=ok&&nvs_get_str(n,"device",device_id,&z)==ESP_OK; z=sizeof(secret); ok=ok&&nvs_get_str(n,"secret",secret,&z)==ESP_OK; z=sizeof(transport); if(nvs_get_str(n,"transport",transport,&z)!=ESP_OK) snprintf(transport,sizeof(transport),"https"); nvs_close(n); remote_status.transport=!strcmp(transport,"mqtt")?METECH_REMOTE_MQTT:METECH_REMOTE_HTTPS; return ok&&((remote_status.transport==METECH_REMOTE_HTTPS&&!strncmp(endpoint,"https://",8))||(remote_status.transport==METECH_REMOTE_MQTT&&!strncmp(endpoint,"mqtts://",8)))&&strlen(secret)>=32; }
static void hex_nonce(char out[33]) { static const char h[]="0123456789abcdef"; for(int i=0;i<16;i++){unsigned v=esp_random()&255;out[i*2]=h[v>>4];out[i*2+1]=h[v&15];}out[32]=0; }
static bool signature(const char *stamp,const char *nonce,const char *body,char out[65]) { unsigned char sum[32]; char input[256]; int n=snprintf(input,sizeof(input),"%s\n%s\n%s",stamp,nonce,body); if(n<0||n>=(int)sizeof(input))return false; const mbedtls_md_info_t *md=mbedtls_md_info_from_type(MBEDTLS_MD_SHA256); if(!md||mbedtls_md_hmac(md,(const unsigned char*)secret,strlen(secret),(const unsigned char*)input,n,sum))return false; for(int i=0;i<32;i++)sprintf(out+i*2,"%02x",sum[i]);out[64]=0;return true; }
static bool post_json(const char *path,const char *body,char *reply,size_t cap) { char stamp[16],nonce[33],sig[65],url[REMOTE_ENDPOINT_MAX+32]; snprintf(stamp,sizeof(stamp),"%lld",(long long)time(NULL));hex_nonce(nonce);if(!signature(stamp,nonce,body,sig))return false;snprintf(url,sizeof(url),"%s%s",endpoint,path); esp_http_client_config_t cfg={.url=url,.timeout_ms=8000,.crt_bundle_attach=esp_crt_bundle_attach};esp_http_client_handle_t c=esp_http_client_init(&cfg);if(!c)return false;esp_http_client_set_method(c,HTTP_METHOD_POST);esp_http_client_set_header(c,"Content-Type","application/json");esp_http_client_set_header(c,"X-Metech-Device",device_id);esp_http_client_set_header(c,"X-Metech-Time",stamp);esp_http_client_set_header(c,"X-Metech-Nonce",nonce);esp_http_client_set_header(c,"X-Metech-Signature",sig);esp_http_client_set_post_field(c,body,strlen(body));esp_err_t e=esp_http_client_perform(c);int code=esp_http_client_get_status_code(c);int got=e==ESP_OK&&code==200?esp_http_client_read_response(c,reply,cap-1):-1;if(got>=0)reply[got]=0;esp_http_client_cleanup(c);return got>=0; }
static void remote_task(void *arg) { char reply[256],body[160]; unsigned delay=1; for(;;){if(time(NULL)<1700000000){remote_set(METECH_REMOTE_WAIT_CLOCK,"clock unsynced",30);vTaskDelay(pdMS_TO_TICKS(30000));continue;}remote_set(METECH_REMOTE_CONNECTING,"",0);snprintf(body,sizeof(body),"{\"uptime_s\":%llu,\"transport\":\"https\"}",(unsigned long long)(esp_timer_get_time()/1000000ULL));bool ok=post_json("/v1/device/heartbeat",body,reply,sizeof(reply))&&post_json("/v1/device/poll","{}",reply,sizeof(reply));if(ok){if(xSemaphoreTake(remote_lock,pdMS_TO_TICKS(50))==pdTRUE){remote_status.state=METECH_REMOTE_READY;remote_status.attempts=0;remote_status.last_success_s=(unsigned)(esp_timer_get_time()/1000000ULL);remote_status.error[0]=0;xSemaphoreGive(remote_lock);}delay=5;}else{if(xSemaphoreTake(remote_lock,pdMS_TO_TICKS(50))==pdTRUE){remote_status.attempts++;xSemaphoreGive(remote_lock);}remote_set(METECH_REMOTE_COOLDOWN,"https request failed",delay);delay=delay<60?delay*2:60;}vTaskDelay(pdMS_TO_TICKS(delay*1000));} }
bool metech_remote_init(void) { remote_lock=xSemaphoreCreateMutex();if(!remote_lock)return false;remote_status.enabled=load_config();if(!remote_status.enabled)remote_set(METECH_REMOTE_DISABLED,"not provisioned",0);return true; }
static void mqtt_event(void *arg, esp_event_base_t base, int32_t id, void *data) { esp_mqtt_event_handle_t e=data; if(id==MQTT_EVENT_CONNECTED){char topic[80];snprintf(topic,sizeof(topic),"metech/%s/command",device_id);esp_mqtt_client_subscribe(e->client,topic,1);remote_set(METECH_REMOTE_READY,"",0);}else if(id==MQTT_EVENT_ERROR)remote_set(METECH_REMOTE_COOLDOWN,"mqtt connection failed",30); }
static void start_mqtt(void) { esp_mqtt_client_config_t cfg={.broker.address.uri=endpoint,.broker.verification.crt_bundle_attach=esp_crt_bundle_attach,.credentials.username=device_id,.credentials.authentication.password=secret,.credentials.client_id=device_id,.session.keepalive=30};mqtt_client=esp_mqtt_client_init(&cfg);if(!mqtt_client){remote_set(METECH_REMOTE_COOLDOWN,"mqtt init failed",30);return;}esp_mqtt_client_register_event(mqtt_client,ESP_EVENT_ANY_ID,mqtt_event,NULL);esp_mqtt_client_start(mqtt_client); }
void metech_remote_start(void) { if(!remote_status.enabled)return; if(remote_status.transport==METECH_REMOTE_MQTT){start_mqtt();return;} xTaskCreate(remote_task,"metech_remote",6144,NULL,3,NULL); }
