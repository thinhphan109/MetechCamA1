#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
typedef enum { METECH_JOB_IDLE, METECH_JOB_RUNNING, METECH_JOB_READY, METECH_JOB_FAILED, METECH_JOB_COOLDOWN } metech_job_state_t;
typedef struct { SemaphoreHandle_t lock; metech_job_state_t state; uint32_t attempts, updated_s, retry_after_s; esp_err_t error; } metech_job_t;
bool metech_job_init(metech_job_t *job); bool metech_job_begin(metech_job_t *job); void metech_job_succeed(metech_job_t *job); void metech_job_fail(metech_job_t *job, esp_err_t error, uint32_t cooldown_ms); void metech_job_snapshot(metech_job_t *job, metech_job_t *out); uint32_t metech_retry_delay_ms(uint32_t attempts, uint32_t initial_ms, uint32_t maximum_ms); const char *metech_job_state_name(metech_job_state_t state); void metech_json_append_string(char *out, size_t size, size_t *used, const char *value);
