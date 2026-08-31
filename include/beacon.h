#ifndef BEACON_H
#define BEACON_H

#include <stddef.h>
#include <stdint.h>

enum {
    BEACON_KEY_BYTES = 28,
    BEACON_ADDRESS_BYTES = 6,
    BEACON_MANUFACTURER_PAYLOAD_BYTES = 29,
    BEACON_AD_BYTES = 31
};

enum beacon_result {
    BEACON_OK = 0,
    BEACON_ERR_ARGUMENT = -1,
    BEACON_ERR_KEY_COUNT = -2,
    BEACON_ERR_REUSE_CYCLES = -3,
    BEACON_ERR_ADDRESS = -4
};

struct beacon_rotation_state {
    size_t key_index;
    uint32_t cycle;
};

int beacon_address_from_key(const uint8_t key[BEACON_KEY_BYTES],
                            uint8_t address[BEACON_ADDRESS_BYTES]);

int beacon_key_table_validate(
    const uint8_t (*keys)[BEACON_KEY_BYTES], size_t key_count,
    size_t configured_max);

int beacon_manufacturer_payload_from_key(
    const uint8_t key[BEACON_KEY_BYTES],
    uint8_t payload[BEACON_MANUFACTURER_PAYLOAD_BYTES], uint8_t state);

int beacon_ad_from_key(const uint8_t key[BEACON_KEY_BYTES],
                       uint8_t ad[BEACON_AD_BYTES], uint8_t state);

void beacon_rotation_init(struct beacon_rotation_state *rotation);

/*
 * Advances the persistent scheduler state after a use of key_index.
 * Starting at {0, 0}, reuse_cycles == 1 yields upstream-style uses of
 * index 0 at startup and index 1 after the first advance.
 */
int beacon_rotation_advance(struct beacon_rotation_state *rotation,
                            size_t key_count, uint32_t reuse_cycles);

#endif
