#ifndef RADIO_CYCLE_H
#define RADIO_CYCLE_H

#include <stddef.h>
#include <stdint.h>

#include "beacon.h"

struct radio_cycle_config {
    size_t key_count;
    uint32_t reuse_cycles;
    uint32_t advertise_seconds;
    uint32_t sleep_seconds;
    uint16_t interval_units;
};

struct radio_cycle_ops {
    int (*start)(void *context, size_t key_index, uint16_t interval_units);
    int (*stop)(void *context);
    int (*reset)(void *context, size_t next_key_index);
    void (*sleep)(void *context, uint32_t seconds);
    void *context;
};

int radio_cycle_run_once(struct beacon_rotation_state *rotation,
                         const struct radio_cycle_config *config,
                         const struct radio_cycle_ops *ops);

#endif
