#include "beacon.h"

#include <stdbool.h>
#include <string.h>

int beacon_address_from_key(const uint8_t key[BEACON_KEY_BYTES],
                            uint8_t address[BEACON_ADDRESS_BYTES])
{
    bool all_zero;
    bool all_one;
    size_t index;

    if (key == NULL || address == NULL) {
        return BEACON_ERR_ARGUMENT;
    }

    all_zero = (key[0] & 0x3fU) == 0U;
    all_one = (key[0] & 0x3fU) == 0x3fU;
    for (index = 1U; index < BEACON_ADDRESS_BYTES; ++index) {
        all_zero = all_zero && key[index] == 0U;
        all_one = all_one && key[index] == 0xffU;
    }
    if (all_zero || all_one) {
        return BEACON_ERR_ADDRESS;
    }

    address[0] = key[5];
    address[1] = key[4];
    address[2] = key[3];
    address[3] = key[2];
    address[4] = key[1];
    address[5] = (uint8_t)(key[0] | 0xc0U);
    return BEACON_OK;
}

int beacon_key_table_validate(
    const uint8_t (*keys)[BEACON_KEY_BYTES], size_t key_count,
    size_t configured_max)
{
    uint8_t address[BEACON_ADDRESS_BYTES];
    size_t index;
    int result;

    if (keys == NULL) {
        return BEACON_ERR_ARGUMENT;
    }
    if (key_count == 0U || key_count > configured_max) {
        return BEACON_ERR_KEY_COUNT;
    }

    for (index = 0U; index < key_count; ++index) {
        result = beacon_address_from_key(keys[index], address);
        if (result != BEACON_OK) {
            return result;
        }
    }

    return BEACON_OK;
}

int beacon_manufacturer_payload_from_key(
    const uint8_t key[BEACON_KEY_BYTES],
    uint8_t payload[BEACON_MANUFACTURER_PAYLOAD_BYTES], uint8_t state)
{
    if (key == NULL || payload == NULL) {
        return BEACON_ERR_ARGUMENT;
    }

    payload[0] = 0x4cU;
    payload[1] = 0x00U;
    payload[2] = 0x12U;
    payload[3] = 0x19U;
    payload[4] = state;
    memcpy(&payload[5], &key[6], 22U);
    payload[27] = (uint8_t)(key[0] >> 6U);
    payload[28] = 0x00U;
    return BEACON_OK;
}

int beacon_ad_from_key(const uint8_t key[BEACON_KEY_BYTES],
                       uint8_t ad[BEACON_AD_BYTES], uint8_t state)
{
    int result;

    if (ad == NULL) {
        return BEACON_ERR_ARGUMENT;
    }

    ad[0] = 0x1eU;
    ad[1] = 0xffU;
    result = beacon_manufacturer_payload_from_key(key, &ad[2], state);
    return result;
}

void beacon_rotation_init(struct beacon_rotation_state *rotation)
{
    if (rotation != NULL) {
        rotation->key_index = 0U;
        rotation->cycle = 0U;
    }
}

int beacon_rotation_advance(struct beacon_rotation_state *rotation,
                            size_t key_count, uint32_t reuse_cycles)
{
    if (rotation == NULL) {
        return BEACON_ERR_ARGUMENT;
    }
    if (key_count == 0U) {
        return BEACON_ERR_KEY_COUNT;
    }
    if (reuse_cycles == 0U) {
        return BEACON_ERR_REUSE_CYCLES;
    }

    rotation->key_index %= key_count;
    rotation->cycle += 1U;
    if (rotation->cycle >= reuse_cycles) {
        rotation->cycle = 0U;
        rotation->key_index = (rotation->key_index + 1U) % key_count;
    }
    return BEACON_OK;
}
