#pragma once
#include <stdbool.h>
#include <stddef.h>

typedef enum { METECH_REMOTE_DISABLED, METECH_REMOTE_WAIT_CLOCK, METECH_REMOTE_CONNECTING, METECH_REMOTE_READY, METECH_REMOTE_COOLDOWN } metech_remote_state_t;
typedef enum { METECH_REMOTE_HTTPS, METECH_REMOTE_MQTT } metech_remote_transport_t;
typedef struct { metech_remote_state_t state; bool enabled; metech_remote_transport_t transport; unsigned attempts; unsigned last_success_s; unsigned retry_after_s; char error[40]; } metech_remote_status_t;

bool metech_remote_init(void);
void metech_remote_start(void);
void metech_remote_status(metech_remote_status_t *out);
const char *metech_remote_state_name(metech_remote_state_t state);
const char *metech_remote_transport_name(metech_remote_transport_t transport);
