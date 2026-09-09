#include "metech_reliability.h"
#include <string.h>
#include "esp_timer.h"
static uint32_t now_s(void) { return (uint32_t)(esp_timer_get_time() / 1000000ULL); }
bool metech_job_init(metech_job_t *job) { memset(job, 0, sizeof(*job)); job->lock=xSemaphoreCreateMutex(); return job->lock!=NULL; }
bool metech_job_begin(metech_job_t *job) { bool allowed=false; xSemaphoreTake(job->lock,portMAX_DELAY); uint32_t now=now_s(); if(job->state!=METECH_JOB_RUNNING&&(job->state!=METECH_JOB_COOLDOWN||now>=job->retry_after_s)){job->state=METECH_JOB_RUNNING;job->attempts++;job->updated_s=now;job->error=ESP_OK;allowed=true;}xSemaphoreGive(job->lock);return allowed; }
void metech_job_succeed(metech_job_t *job) { xSemaphoreTake(job->lock,portMAX_DELAY);job->state=METECH_JOB_READY;job->updated_s=now_s();job->retry_after_s=0;job->error=ESP_OK;xSemaphoreGive(job->lock); }
void metech_job_fail(metech_job_t *job,esp_err_t error,uint32_t cooldown_ms) { xSemaphoreTake(job->lock,portMAX_DELAY);job->state=cooldown_ms?METECH_JOB_COOLDOWN:METECH_JOB_FAILED;job->updated_s=now_s();job->retry_after_s=job->updated_s+(cooldown_ms+999)/1000;job->error=error;xSemaphoreGive(job->lock); }
void metech_job_snapshot(metech_job_t *job,metech_job_t *out) { xSemaphoreTake(job->lock,portMAX_DELAY);*out=*job;out->lock=NULL;xSemaphoreGive(job->lock); }
uint32_t metech_retry_delay_ms(uint32_t attempts,uint32_t initial_ms,uint32_t maximum_ms) { uint32_t delay=initial_ms;while(attempts-->1&&delay<maximum_ms/2)delay*=2;return delay>maximum_ms?maximum_ms:delay; }
const char *metech_job_state_name(metech_job_state_t state) { static const char *names[]={"idle","running","ready","failed","cooldown"};return state<=METECH_JOB_COOLDOWN?names[state]:"failed"; }
void metech_json_append_string(char *out,size_t size,size_t *used,const char *value) { if(*used+2>=size)return;out[(*used)++]='\"';for(;*value&&*used+7<size;value++){unsigned char c=(unsigned char)*value;if(c=='\"'||c=='\\'){out[(*used)++]='\\';out[(*used)++]=c;}else if(c>=0x20)out[(*used)++]=c;}out[(*used)++]='\"';out[*used]=0; }
