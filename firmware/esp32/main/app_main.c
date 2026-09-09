#include <dirent.h>
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "esp_camera.h"
#include "esp_camera_af.h"
#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_psram.h"
#include "esp_timer.h"
#include "esp_vfs_fat.h"
#include "esp_wifi.h"
#include "driver/sdmmc_host.h"
#include "driver/spi_master.h"
#include "driver/sdspi_host.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "sdmmc_cmd.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#include "board_profile.h"
#include "network_defaults.h"
#include "trigger.h"
#include "web_ui.h"

#define METECH_AP_SSID METECH_RECOVERY_AP_SSID
#define METECH_AP_PASSWORD METECH_RECOVERY_AP_PASSWORD
#define METECH_AP_CHANNEL 1
#define METECH_SD_MOUNT "/sdcard"

static const char *TAG = "metech_camera";
static SemaphoreHandle_t camera_lock;
static esp_netif_t *sta_netif;
static volatile uint32_t preview_captures;
static uint32_t saved_captures;
static const char *autofocus_status = "not-tested";
static char wifi_ssid[33];
static char wifi_state[24] = "not configured";
static char wifi_ip[16] = "-";
static char sd_state[48] = "not tested";
static bool sd_ready;
static sdmmc_card_t *sd_card;
static uint32_t gallery_images;
static uint32_t cleaned_tmp_files;
typedef struct {
    int8_t brightness, contrast, saturation, sharpness, quality;
    bool awb, exposure, gain;
} camera_settings_t;
static camera_settings_t camera_settings = {.brightness = 1, .contrast = 0, .saturation = 0, .sharpness = 0, .quality = 10, .awb = true, .exposure = true, .gain = true};

static camera_config_t camera_config(void) {
    return (camera_config_t){
        .ledc_channel = LEDC_CHANNEL_0, .ledc_timer = LEDC_TIMER_0,
        .pin_d0 = METECH_CAM_Y2, .pin_d1 = METECH_CAM_Y3, .pin_d2 = METECH_CAM_Y4,
        .pin_d3 = METECH_CAM_Y5, .pin_d4 = METECH_CAM_Y6, .pin_d5 = METECH_CAM_Y7,
        .pin_d6 = METECH_CAM_Y8, .pin_d7 = METECH_CAM_Y9, .pin_xclk = METECH_CAM_XCLK,
        .pin_pclk = METECH_CAM_PCLK, .pin_vsync = METECH_CAM_VSYNC, .pin_href = METECH_CAM_HREF,
        .pin_sccb_sda = METECH_CAM_SIOD, .pin_sccb_scl = METECH_CAM_SIOC,
        .pin_pwdn = METECH_CAM_PWDN, .pin_reset = METECH_CAM_RESET, .xclk_freq_hz = 10000000,
        .pixel_format = PIXFORMAT_JPEG, .frame_size = FRAMESIZE_QSXGA, .jpeg_quality = 10,
        .fb_count = 1, .fb_location = CAMERA_FB_IN_PSRAM, .grab_mode = CAMERA_GRAB_WHEN_EMPTY,
    };
}

static bool valid_settings(const camera_settings_t *s) {
    return s->brightness >= -2 && s->brightness <= 2 && s->contrast >= -2 && s->contrast <= 2 &&
           s->saturation >= -2 && s->saturation <= 2 && s->sharpness >= -2 && s->sharpness <= 2 &&
           s->quality >= 8 && s->quality <= 20;
}

static esp_err_t apply_camera_settings(void) {
    sensor_t *sensor = esp_camera_sensor_get();
    if (!sensor || !valid_settings(&camera_settings)) return ESP_ERR_INVALID_STATE;
    if (sensor->set_brightness(sensor, camera_settings.brightness) || sensor->set_contrast(sensor, camera_settings.contrast) ||
        sensor->set_saturation(sensor, camera_settings.saturation) || sensor->set_sharpness(sensor, camera_settings.sharpness) ||
        sensor->set_quality(sensor, camera_settings.quality) || sensor->set_whitebal(sensor, camera_settings.awb) ||
        sensor->set_awb_gain(sensor, camera_settings.awb) || sensor->set_exposure_ctrl(sensor, camera_settings.exposure) ||
        sensor->set_gain_ctrl(sensor, camera_settings.gain)) return ESP_FAIL;
    return ESP_OK;
}

static void nvs_load_camera_settings(void) {
    nvs_handle_t nvs;
    size_t size = sizeof(camera_settings);
    if (nvs_open("metech", NVS_READONLY, &nvs) == ESP_OK) {
        if (nvs_get_blob(nvs, "camera_set", &camera_settings, &size) != ESP_OK || size != sizeof(camera_settings) || !valid_settings(&camera_settings)) {
            camera_settings = (camera_settings_t){.brightness = 1, .contrast = 0, .saturation = 0, .sharpness = 0, .quality = 10, .awb = true, .exposure = true, .gain = true};
        }
        nvs_close(nvs);
    }
}

static esp_err_t nvs_save_camera_settings(void) {
    nvs_handle_t nvs;
    esp_err_t err = nvs_open("metech", NVS_READWRITE, &nvs);
    if (err == ESP_OK) {
        err = nvs_set_blob(nvs, "camera_set", &camera_settings, sizeof(camera_settings));
        if (err == ESP_OK) err = nvs_commit(nvs);
        nvs_close(nvs);
    }
    return err;
}

static void configure_camera(sensor_t *sensor) {
    gpio_set_direction(METECH_ONBOARD_LED, GPIO_MODE_OUTPUT);
    gpio_set_level(METECH_ONBOARD_LED, 1); // GPIO2 LED is active-low; keep it off without affecting the SD bus.
    if (!sensor) return;
    nvs_load_camera_settings();
    apply_camera_settings();
    sensor->set_hmirror(sensor, 1); sensor->set_vflip(sensor, 1); // Physical module is mounted upside down: rotate all JPEG output 180°.
    if (!esp_camera_af_is_supported(sensor)) autofocus_status = "unsupported";
    else { esp_camera_af_config_t af = {.mode = ESP_CAMERA_AF_MODE_AUTO, .timeout_ms = 3000}; autofocus_status = esp_camera_af_init(sensor, &af) == ESP_OK ? "auto" : "failed"; }
    sensor->set_framesize(sensor, FRAMESIZE_SXGA);
}

static void nvs_read_string(const char *key, char *out, size_t size) {
    nvs_handle_t nvs; size_t required = size; out[0] = 0;
    if (nvs_open("metech", NVS_READONLY, &nvs) == ESP_OK) { nvs_get_str(nvs, key, out, &required); nvs_close(nvs); }
}

static esp_err_t nvs_save_wifi(const char *ssid, const char *password) {
    nvs_handle_t nvs; esp_err_t err = nvs_open("metech", NVS_READWRITE, &nvs);
    if (err != ESP_OK) return err;
    err = nvs_set_str(nvs, "wifi_ssid", ssid);
    if (err == ESP_OK) err = nvs_set_str(nvs, "wifi_pass", password);
    if (err == ESP_OK) err = nvs_commit(nvs);
    nvs_close(nvs); return err;
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        strcpy(wifi_state, "reconnecting"); strcpy(wifi_ip, "-");
        if (wifi_ssid[0]) esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        snprintf(wifi_ip, sizeof(wifi_ip), IPSTR, IP2STR(&event->ip_info.ip));
        strcpy(wifi_state, "connected");
        ESP_LOGI(TAG, "Home Wi-Fi connected: http://%s/", wifi_ip);
    }
}

static void connect_home_wifi(void) {
    char password[65]; nvs_read_string("wifi_ssid", wifi_ssid, sizeof(wifi_ssid)); nvs_read_string("wifi_pass", password, sizeof(password));
    if (!wifi_ssid[0]) return;
    wifi_config_t config = {0}; strcpy((char *)config.sta.ssid, wifi_ssid); strcpy((char *)config.sta.password, password);
    esp_wifi_set_config(WIFI_IF_STA, &config); strcpy(wifi_state, "connecting"); esp_wifi_connect();
}

static void start_wifi(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) { ESP_ERROR_CHECK(nvs_flash_erase()); err = nvs_flash_init(); }
    ESP_ERROR_CHECK(err); ESP_ERROR_CHECK(esp_netif_init()); ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_ap(); sta_netif = esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT(); ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event, NULL, NULL));
    wifi_config_t ap = { .ap = { .channel = METECH_AP_CHANNEL, .max_connection = 4, .authmode = WIFI_AUTH_WPA2_PSK } };
    strcpy((char *)ap.ap.ssid, METECH_AP_SSID); strcpy((char *)ap.ap.password, METECH_AP_PASSWORD); ap.ap.ssid_len = strlen(METECH_AP_SSID);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA)); ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap)); ESP_ERROR_CHECK(esp_wifi_start());
    connect_home_wifi(); ESP_LOGI(TAG, "Recovery Wi-Fi '%s': http://192.168.4.1/", METECH_AP_SSID);
}

static bool camera_file_name(const char *name, const char *extension, uint32_t *sequence) {
    unsigned value;
    if (strlen(name) != 11 || sscanf(name, "C%6u", &value) != 1 || value > 999999) return false;
    char expected[12]; snprintf(expected, sizeof(expected), "C%06u.%s", value, extension);
    if (strcmp(name, expected)) return false;
    if (sequence) *sequence = value;
    return true;
}

static void recover_saved_sequence(void) {
    DIR *dir = opendir(METECH_SD_MOUNT "/DCIM/CAM");
    if (!dir) return; // No camera directory yet is a valid first-run state.
    uint32_t highest = 0; gallery_images = 0; cleaned_tmp_files = 0; struct dirent *entry;
    while ((entry = readdir(dir))) {
        uint32_t sequence;
        if (camera_file_name(entry->d_name, "JPG", &sequence)) {
            gallery_images++;
            if (sequence > highest) highest = sequence;
        } else if (camera_file_name(entry->d_name, "TMP", &sequence)) {
            char path[96]; snprintf(path, sizeof(path), METECH_SD_MOUNT "/DCIM/CAM/C%06" PRIu32 ".TMP", sequence);
            if (unlink(path) == 0) cleaned_tmp_files++;
        }
    }
    closedir(dir); saved_captures = highest;
    ESP_LOGI(TAG, "Recovered %" PRIu32 " camera images; cleaned %" PRIu32 " temporary files", gallery_images, cleaned_tmp_files);
}

static void init_sd(void) {
    esp_vfs_fat_sdmmc_mount_config_t mount = {.format_if_mount_failed = false, .max_files = 4, .allocation_unit_size = 16 * 1024};
    sdmmc_host_t host = SDMMC_HOST_DEFAULT(); host.max_freq_khz = 400;
    sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT(); slot.width = 1;
    slot.clk = METECH_SD_CLK; slot.cmd = METECH_SD_CMD; slot.d0 = METECH_SD_D0;
    slot.flags |= SDMMC_SLOT_FLAG_INTERNAL_PULLUP;
    esp_err_t err = esp_vfs_fat_sdmmc_mount(METECH_SD_MOUNT, &host, &slot, &mount, &sd_card);
    if (err != ESP_OK) { snprintf(sd_state, sizeof(sd_state), "not ready: %s", esp_err_to_name(err)); ESP_LOGW(TAG, "microSD %s", sd_state); return; }
    // FATFS is configured without long filenames: every generated path must remain 8.3.
    if (mkdir(METECH_SD_MOUNT "/DCIM", 0775) && errno != EEXIST) { snprintf(sd_state, sizeof(sd_state), "healthcheck DCIM mkdir: %d", errno); goto failed; }
    if (mkdir(METECH_SD_MOUNT "/DCIM/MTEST", 0775) && errno != EEXIST) { snprintf(sd_state, sizeof(sd_state), "healthcheck test mkdir: %d", errno); goto failed; }
    const char expected[] = "Metech microSD healthcheck v1\n"; char part[96], final[96], readback[sizeof(expected)];
    uint32_t stamp = (uint32_t)esp_timer_get_time() & 0x00ffffff;
    snprintf(part, sizeof(part), METECH_SD_MOUNT "/DCIM/MTEST/HC%06" PRIX32 ".TMP", stamp);
    snprintf(final, sizeof(final), METECH_SD_MOUNT "/DCIM/MTEST/HC%06" PRIX32 ".TXT", stamp);
    FILE *file = fopen(part, "wb");
    if (!file) { snprintf(sd_state, sizeof(sd_state), "healthcheck open failed"); goto failed; }
    if (fwrite(expected, 1, sizeof(expected), file) != sizeof(expected) || fsync(fileno(file))) { fclose(file); unlink(part); snprintf(sd_state, sizeof(sd_state), "healthcheck write failed"); goto failed; }
    if (fclose(file)) { unlink(part); snprintf(sd_state, sizeof(sd_state), "healthcheck close failed"); goto failed; }
    if (rename(part, final)) { unlink(part); snprintf(sd_state, sizeof(sd_state), "healthcheck rename failed"); goto failed; }
    file = fopen(final, "rb");
    if (!file) { snprintf(sd_state, sizeof(sd_state), "healthcheck reopen failed"); goto failed; }
    size_t bytes_read = fread(readback, 1, sizeof(readback), file);
    if (fclose(file) || bytes_read != sizeof(readback) || memcmp(expected, readback, sizeof(expected))) { snprintf(sd_state, sizeof(sd_state), "healthcheck readback failed"); goto failed; }
    recover_saved_sequence();
    sd_ready = true; strcpy(sd_state, "ready and checked"); sdmmc_card_print_info(stdout, sd_card); return;
failed: if (strcmp(sd_state, "healthcheck failed") == 0) strcpy(sd_state, "healthcheck setup failed"); esp_vfs_fat_sdcard_unmount(METECH_SD_MOUNT, sd_card); sd_card = NULL;
}

static esp_err_t capture_to_sd(char *saved, size_t saved_size) {
    if (!sd_ready) return ESP_ERR_INVALID_STATE;
    if (xSemaphoreTake(camera_lock, pdMS_TO_TICKS(5000)) != pdTRUE) return ESP_ERR_TIMEOUT;
    sensor_t *sensor = esp_camera_sensor_get(); sensor->set_framesize(sensor, FRAMESIZE_QSXGA); camera_fb_t *frame = esp_camera_fb_get();
    if (!frame) { sensor->set_framesize(sensor, FRAMESIZE_SXGA); xSemaphoreGive(camera_lock); return ESP_FAIL; }
    if (mkdir(METECH_SD_MOUNT "/DCIM/CAM", 0775) && errno != EEXIST) { esp_camera_fb_return(frame); sensor->set_framesize(sensor, FRAMESIZE_SXGA); xSemaphoreGive(camera_lock); return ESP_FAIL; }
    char part[96];
    uint32_t sequence = saved_captures + 1;
    snprintf(saved, saved_size, METECH_SD_MOUNT "/DCIM/CAM/C%06" PRIu32 ".JPG", sequence);
    snprintf(part, sizeof(part), METECH_SD_MOUNT "/DCIM/CAM/C%06" PRIu32 ".TMP", sequence);
    FILE *file = fopen(part, "wb");
    bool ok = false;
    if (file) {
        bool written = fwrite(frame->buf, 1, frame->len, file) == frame->len;
        bool synced = written && fsync(fileno(file)) == 0;
        bool closed = fclose(file) == 0;
        if (synced && closed && rename(part, saved) == 0) { saved_captures = sequence; gallery_images++; ok = true; }
    }
    if (!ok) unlink(part);
    esp_camera_fb_return(frame); sensor->set_framesize(sensor, FRAMESIZE_SXGA); xSemaphoreGive(camera_lock); return ok ? ESP_OK : ESP_FAIL;
}

static esp_err_t index_handler(httpd_req_t *r) { httpd_resp_set_type(r, "text/html; charset=utf-8"); return httpd_resp_send(r, METECH_WEB_UI, HTTPD_RESP_USE_STRLEN); }
static esp_err_t status_handler(httpd_req_t *r) {
    char body[440]; uint64_t uptime_s = esp_timer_get_time() / 1000000ULL;
    int n = snprintf(body, sizeof(body), "{\"width\":1280,\"height\":1024,\"captures\":%" PRIu32 ",\"wifi\":\"%s\",\"ip\":\"%s\",\"ssid\":\"%s\",\"sd\":\"%s\",\"sd_ready\":%s,\"saved\":%" PRIu32 ",\"images\":%" PRIu32 ",\"tmp_cleaned\":%" PRIu32 ",\"uptime_s\":%" PRIu64 ",\"resolution\":\"2592x1944\",\"camera_mode\":\"auto white balance, auto exposure, auto gain\",\"autofocus\":\"%s\"}", preview_captures, wifi_state, wifi_ip, wifi_ssid, sd_state, sd_ready ? "true" : "false", saved_captures, gallery_images, cleaned_tmp_files, uptime_s, autofocus_status);
    httpd_resp_set_type(r, "application/json"); return httpd_resp_send(r, body, n);
}
static esp_err_t jpeg_handler(httpd_req_t *r, framesize_t size) { if (xSemaphoreTake(camera_lock, pdMS_TO_TICKS(3000)) != pdTRUE) return httpd_resp_send_err(r, HTTPD_500_INTERNAL_SERVER_ERROR, "Camera busy"); sensor_t *s = esp_camera_sensor_get(); s->set_framesize(s,size); camera_fb_t *f=esp_camera_fb_get(); if(!f){s->set_framesize(s,FRAMESIZE_SXGA);xSemaphoreGive(camera_lock);return httpd_resp_send_err(r,HTTPD_500_INTERNAL_SERVER_ERROR,"Capture failed");} httpd_resp_set_type(r,"image/jpeg"); httpd_resp_set_hdr(r,"Cache-Control","no-store"); esp_err_t e=httpd_resp_send(r,(const char*)f->buf,f->len); esp_camera_fb_return(f);s->set_framesize(s,FRAMESIZE_SXGA);xSemaphoreGive(camera_lock);return e; }
static esp_err_t snapshot_handler(httpd_req_t *r) { esp_err_t e=jpeg_handler(r,FRAMESIZE_SXGA); if(e==ESP_OK)preview_captures++; return e; }
static esp_err_t still_handler(httpd_req_t *r) { return jpeg_handler(r,FRAMESIZE_QSXGA); }
static esp_err_t gallery_handler(httpd_req_t *r) {
    char body[600];
    size_t used = (size_t)snprintf(body, sizeof(body), "{\"images\":[");
    bool first = true;
    size_t shown = 0;
    // FATFS directory iteration may yield transient empty listings while camera preview requests are active.
    // Camera-owned image names are sequential and recovered at boot, so verify files by their exact path instead.
    for (uint32_t sequence = saved_captures; sequence && shown < 24; sequence--) {
        char path[96];
        snprintf(path, sizeof(path), METECH_SD_MOUNT "/DCIM/CAM/C%06" PRIu32 ".JPG", sequence);
        FILE *file = fopen(path, "rb");
        if (!file) continue;
        fclose(file);
        used += (size_t)snprintf(body + used, sizeof(body) - used, "%s\"C%06" PRIu32 ".JPG\"", first ? "" : ",", sequence);
        first = false;
        shown++;
    }
    used += (size_t)snprintf(body + used, sizeof(body) - used, "],\"total\":%" PRIu32 "}", gallery_images);
    httpd_resp_set_type(r, "application/json");
    return httpd_resp_send(r, body, used);
}
static esp_err_t image_handler(httpd_req_t *r) {
    const char *name = r->uri + strlen("/image/");
    uint32_t sequence;
    if (!sd_ready || !camera_file_name(name, "JPG", &sequence)) return httpd_resp_send_err(r, HTTPD_404_NOT_FOUND, "Image not found");
    char path[96];
    snprintf(path, sizeof(path), METECH_SD_MOUNT "/DCIM/CAM/C%06" PRIu32 ".JPG", sequence);
    FILE *file = fopen(path, "rb");
    if (!file) return httpd_resp_send_err(r, HTTPD_404_NOT_FOUND, "Image not found");
    httpd_resp_set_type(r, "image/jpeg");
    char buffer[1024];
    size_t read;
    while ((read = fread(buffer, 1, sizeof(buffer), file)) > 0) {
        if (httpd_resp_send_chunk(r, buffer, read) != ESP_OK) {
            fclose(file);
            return ESP_FAIL;
        }
    }
    fclose(file);
    return httpd_resp_send_chunk(r, NULL, 0);
}
static int form_value(const char *body, const char *key, char *out, size_t size) { const char *p=strstr(body,key); if(!p || strncmp(p+strlen(key),"=",1))return 0; p+=strlen(key)+1; size_t n=0; while(*p&&*p!='&'&&n+1<size){if(*p=='+')out[n++]=' ';else out[n++]=*p++;}out[n]=0;return n>0; }
static esp_err_t wifi_handler(httpd_req_t *r) { char body[160]={0},ssid[33]={0},pass[65]={0}; if(r->content_len>=sizeof(body)||httpd_req_recv(r,body,r->content_len)<=0||!form_value(body,"ssid",ssid,sizeof(ssid))||!form_value(body,"password",pass,sizeof(pass)))return httpd_resp_send_err(r,HTTPD_400_BAD_REQUEST,"Invalid Wi-Fi details"); esp_err_t e=nvs_save_wifi(ssid,pass); if(e==ESP_OK){strcpy(wifi_ssid,ssid);wifi_config_t c={0};strcpy((char*)c.sta.ssid,ssid);strcpy((char*)c.sta.password,pass);esp_wifi_set_config(WIFI_IF_STA,&c);strcpy(wifi_state,"connecting");esp_wifi_connect();} return httpd_resp_sendstr(r,e==ESP_OK?"Saved; connecting":"Could not save"); }
static void camera_settings_json(char *body, size_t size) {
    snprintf(body, size, "{\"brightness\":%d,\"contrast\":%d,\"saturation\":%d,\"sharpness\":%d,\"quality\":%d,\"awb\":%s,\"exposure\":%s,\"gain\":%s}",
             camera_settings.brightness, camera_settings.contrast, camera_settings.saturation, camera_settings.sharpness, camera_settings.quality,
             camera_settings.awb ? "true" : "false", camera_settings.exposure ? "true" : "false", camera_settings.gain ? "true" : "false");
}

static esp_err_t camera_settings_handler(httpd_req_t *r) {
    char body[160];
    camera_settings_json(body, sizeof(body));
    httpd_resp_set_type(r, "application/json");
    return httpd_resp_sendstr(r, body);
}

static esp_err_t camera_settings_update_handler(httpd_req_t *r) {
    char body[192] = {0};
    char value[16] = {0};
    camera_settings_t next = camera_settings;
    if (r->content_len >= sizeof(body) || httpd_req_recv(r, body, r->content_len) <= 0 || !form_value(body, "name", value, sizeof(value))) {
        return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "Invalid camera setting");
    }
    char setting_value[16] = {0};
    if (!form_value(body, "value", setting_value, sizeof(setting_value))) return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "Missing setting value");
    int number = atoi(setting_value);
    if (!strcmp(value, "brightness")) next.brightness = number;
    else if (!strcmp(value, "contrast")) next.contrast = number;
    else if (!strcmp(value, "saturation")) next.saturation = number;
    else if (!strcmp(value, "sharpness")) next.sharpness = number;
    else if (!strcmp(value, "quality")) next.quality = number;
    else if (!strcmp(value, "awb")) next.awb = number == 1;
    else if (!strcmp(value, "exposure")) next.exposure = number == 1;
    else if (!strcmp(value, "gain")) next.gain = number == 1;
    else return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "Unknown camera setting");
    if (!valid_settings(&next) || (strcmp(value, "awb") == 0 && number != 0 && number != 1) ||
        (strcmp(value, "exposure") == 0 && number != 0 && number != 1) || (strcmp(value, "gain") == 0 && number != 0 && number != 1)) {
        return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "Camera setting out of range");
    }
    if (xSemaphoreTake(camera_lock, pdMS_TO_TICKS(3000)) != pdTRUE) return httpd_resp_send_err(r, HTTPD_500_INTERNAL_SERVER_ERROR, "Camera busy");
    camera_settings = next;
    esp_err_t err = apply_camera_settings();
    xSemaphoreGive(camera_lock);
    if (err != ESP_OK) return httpd_resp_send_err(r, HTTPD_500_INTERNAL_SERVER_ERROR, "Could not apply camera setting");
    char response[160];
    camera_settings_json(response, sizeof(response));
    httpd_resp_set_type(r, "application/json");
    return httpd_resp_sendstr(r, response);
}

static esp_err_t camera_profile_handler(httpd_req_t *r) {
    char body[64] = {0}, profile[16] = {0};
    if (r->content_len >= sizeof(body) || httpd_req_recv(r, body, r->content_len) <= 0 || !form_value(body, "profile", profile, sizeof(profile))) return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "Invalid camera profile");
    if (!strcmp(profile, "auto")) camera_settings = (camera_settings_t){.brightness = 1, .contrast = 0, .saturation = 0, .sharpness = 0, .quality = 10, .awb = true, .exposure = true, .gain = true};
    else if (!strcmp(profile, "bright")) camera_settings = (camera_settings_t){.brightness = 2, .contrast = 1, .saturation = 0, .sharpness = 0, .quality = 10, .awb = true, .exposure = true, .gain = true};
    else if (!strcmp(profile, "neutral")) camera_settings = (camera_settings_t){.brightness = 0, .contrast = 0, .saturation = 0, .sharpness = 0, .quality = 10, .awb = true, .exposure = true, .gain = true};
    else return httpd_resp_send_err(r, HTTPD_400_BAD_REQUEST, "Unknown camera profile");
    if (xSemaphoreTake(camera_lock, pdMS_TO_TICKS(3000)) != pdTRUE) return httpd_resp_send_err(r, HTTPD_500_INTERNAL_SERVER_ERROR, "Camera busy");
    esp_err_t err = apply_camera_settings();
    xSemaphoreGive(camera_lock);
    if (err != ESP_OK) return httpd_resp_send_err(r, HTTPD_500_INTERNAL_SERVER_ERROR, "Could not apply camera profile");
    char response[160];
    camera_settings_json(response, sizeof(response));
    httpd_resp_set_type(r, "application/json");
    return httpd_resp_sendstr(r, response);
}

static esp_err_t camera_settings_save_handler(httpd_req_t *r) {
    return nvs_save_camera_settings() == ESP_OK ? httpd_resp_sendstr(r, "Camera settings saved") : httpd_resp_send_err(r, HTTPD_500_INTERNAL_SERVER_ERROR, "Could not save camera settings");
}

static esp_err_t capture_handler(httpd_req_t *r) { char path[96]; esp_err_t e=capture_to_sd(path,sizeof(path)); if(e!=ESP_OK)return httpd_resp_send_err(r,HTTPD_500_INTERNAL_SERVER_ERROR,"SD capture failed"); return httpd_resp_sendstr(r,path + strlen(METECH_SD_MOUNT) + 1); }

static void start_http_server(void) { httpd_handle_t server; httpd_config_t c=HTTPD_DEFAULT_CONFIG(); c.max_uri_handlers=12; c.uri_match_fn=httpd_uri_match_wildcard; ESP_ERROR_CHECK(httpd_start(&server,&c)); const httpd_uri_t u[]={ {.uri="/",.method=HTTP_GET,.handler=index_handler},{.uri="/api/status",.method=HTTP_GET,.handler=status_handler},{.uri="/api/gallery",.method=HTTP_GET,.handler=gallery_handler},{.uri="/image/*",.method=HTTP_GET,.handler=image_handler},{.uri="/snapshot.jpg",.method=HTTP_GET,.handler=snapshot_handler},{.uri="/still.jpg",.method=HTTP_GET,.handler=still_handler},{.uri="/api/wifi",.method=HTTP_POST,.handler=wifi_handler},{.uri="/api/capture",.method=HTTP_POST,.handler=capture_handler},{.uri="/api/camera-settings",.method=HTTP_GET,.handler=camera_settings_handler},{.uri="/api/camera-settings",.method=HTTP_POST,.handler=camera_settings_update_handler},{.uri="/api/camera-profile",.method=HTTP_POST,.handler=camera_profile_handler},{.uri="/api/camera-settings/save",.method=HTTP_POST,.handler=camera_settings_save_handler} }; for(size_t i=0;i<sizeof(u)/sizeof(u[0]);i++) ESP_ERROR_CHECK(httpd_register_uri_handler(server,&u[i])); }

void app_main(void) { if(!esp_psram_is_initialized()){ESP_LOGE(TAG,"PSRAM unavailable");return;} start_wifi(); camera_config_t c=camera_config(); ESP_ERROR_CHECK(esp_camera_init(&c)); configure_camera(esp_camera_sensor_get()); camera_lock=xSemaphoreCreateMutex(); if(!camera_lock)return; init_sd(); start_http_server(); ESP_LOGI(TAG,"Camera ready; home Wi-Fi and microSD status available in WebUI"); }
