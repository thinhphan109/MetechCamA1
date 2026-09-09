#include <assert.h>
#include <stdio.h>
#include "trigger.h"

static trigger_config_t config = {.confirm_ms=15, .settle_ms=300, .release_ms=40, .minimum_interval_ms=5000};
static void tick(trigger_t *t, bool low, unsigned now) { (void)trigger_tick(t, &config, low, now); }
int main(void) {
  trigger_t t; trigger_init(&t, &config, 0); trigger_arm(&t, 0);
  tick(&t, true, 100); tick(&t, false, 110); assert(t.rejected_glitches == 1 && t.captured == 0);
  tick(&t, true, 5000); tick(&t, true, 5015); tick(&t, true, 5315);
  assert(t.captured == 1 && t.state == TRIGGER_WAIT_RELEASE);
  tick(&t, true, 6000); assert(t.captured == 1 && t.suppressed_held == 0);
  tick(&t, false, 6001); tick(&t, false, 6041); assert(t.state == TRIGGER_ARMED);
  tick(&t, true, 7000); assert(t.state == TRIGGER_ARMED);
  puts("trigger tests: OK");
}
