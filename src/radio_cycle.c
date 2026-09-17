#include "radio_cycle.h"

#include <errno.h>

int radio_cycle_run_once(struct beacon_rotation_state *rotation,
                         const struct radio_cycle_config *config,
                         const struct radio_cycle_ops *ops)
{
    int error;

    if (rotation == NULL || config == NULL || ops == NULL ||
        ops->start == NULL || ops->stop == NULL || ops->reset == NULL ||
        ops->sleep == NULL || config->key_count == 0U ||
        config->reuse_cycles == 0U || config->interval_units == 0U ||
        config->advertise_seconds == 0U ||
        rotation->key_index >= config->key_count) {
        return -EINVAL;
    }

    error = ops->start(ops->context, rotation->key_index,
                       config->interval_units);
    if (error != 0) {
        return error;
    }

    ops->sleep(ops->context, config->advertise_seconds);

    error = ops->stop(ops->context);
    if (error != 0) {
        (void)ops->stop(ops->context);
        return error;
    }

    error = beacon_rotation_advance(rotation, config->key_count,
                                    config->reuse_cycles);
    if (error != BEACON_OK) {
        return error;
    }

    error = ops->reset(ops->context, rotation->key_index);
    if (error != 0) {
        return error;
    }

    ops->sleep(ops->context, config->sleep_seconds);
    return 0;
}
