#include "trigger.h"

void trigger_init(trigger_t *t, const trigger_config_t *c, uint32_t now) {
    *t = (trigger_t){
        .state = TRIGGER_DISARMED,
        .state_since_ms = now,
        .last_capture_ms = now - c->minimum_interval_ms,
    };
}

void trigger_arm(trigger_t *t, uint32_t now) {
    t->state = TRIGGER_ARMED;
    t->state_since_ms = now;
}

void trigger_disarm(trigger_t *t, uint32_t now) {
    t->state = TRIGGER_DISARMED;
    t->state_since_ms = now;
}

void trigger_raw_edge(trigger_t *t, bool hall_low, uint32_t now) {
    t->raw_edges++;
    t->last_raw_edge_ms = now;
    if (t->state == TRIGGER_WAIT_RELEASE && hall_low) t->suppressed_held++;
}

trigger_action_t trigger_tick(trigger_t *t, const trigger_config_t *c, bool hall_low, uint32_t now) {
    if (t->state == TRIGGER_DISARMED) return TRIGGER_NO_ACTION;
    switch (t->state) {
    case TRIGGER_ARMED:
        if (hall_low && now - t->last_capture_ms >= c->minimum_interval_ms) {
            t->state = TRIGGER_CONFIRMING;
            t->state_since_ms = now;
        }
        return TRIGGER_NO_ACTION;
    case TRIGGER_CONFIRMING:
        if (!hall_low) {
            t->rejected_glitches++;
            t->state = TRIGGER_ARMED;
        } else if (now - t->state_since_ms >= c->confirm_ms) {
            t->state = TRIGGER_SETTLING;
            t->state_since_ms = now;
        }
        return TRIGGER_NO_ACTION;
    case TRIGGER_SETTLING:
        if (!hall_low) {
            t->rejected_glitches++;
            t->state = TRIGGER_ARMED;
        } else if (now - t->state_since_ms >= c->settle_ms) {
            t->state = TRIGGER_WAIT_RELEASE;
            t->state_since_ms = now;
            t->last_capture_ms = now;
            t->captured++;
            return TRIGGER_CAPTURE;
        }
        return TRIGGER_NO_ACTION;
    case TRIGGER_WAIT_RELEASE:
        if (hall_low) {
            t->release_since_ms = 0;
            return TRIGGER_NO_ACTION;
        }
        if (t->release_since_ms == 0) t->release_since_ms = now;
        if (now - t->release_since_ms >= c->release_ms) {
            t->state = TRIGGER_ARMED;
            t->state_since_ms = now;
            t->release_since_ms = 0;
        }
        return TRIGGER_NO_ACTION;
    default: return TRIGGER_NO_ACTION;
    }
}

const char *trigger_state_name(trigger_state_t state) {
    static const char *names[] = {"DISARMED", "ARMED", "CONFIRMING", "SETTLING", "WAIT_RELEASE"};
    return state <= TRIGGER_WAIT_RELEASE ? names[state] : "UNKNOWN";
}
