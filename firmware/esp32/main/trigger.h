#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef enum {
    TRIGGER_DISARMED,
    TRIGGER_ARMED,
    TRIGGER_CONFIRMING,
    TRIGGER_SETTLING,
    TRIGGER_WAIT_RELEASE,
} trigger_state_t;

typedef struct {
    uint32_t confirm_ms;
    uint32_t settle_ms;
    uint32_t release_ms;
    uint32_t minimum_interval_ms;
} trigger_config_t;

typedef struct {
    trigger_state_t state;
    uint32_t last_raw_edge_ms;
    uint32_t state_since_ms;
    uint32_t release_since_ms;
    uint32_t last_capture_ms;
    uint32_t raw_edges;
    uint32_t rejected_glitches;
    uint32_t captured;
    uint32_t suppressed_held;
} trigger_t;

typedef enum { TRIGGER_NO_ACTION, TRIGGER_CAPTURE } trigger_action_t;

void trigger_init(trigger_t *trigger, const trigger_config_t *config, uint32_t now_ms);
void trigger_arm(trigger_t *trigger, uint32_t now_ms);
void trigger_disarm(trigger_t *trigger, uint32_t now_ms);
void trigger_raw_edge(trigger_t *trigger, bool hall_low, uint32_t now_ms);
trigger_action_t trigger_tick(trigger_t *trigger, const trigger_config_t *config, bool hall_low, uint32_t now_ms);
const char *trigger_state_name(trigger_state_t state);
