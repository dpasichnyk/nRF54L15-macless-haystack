#include "beacon.h"

#include <assert.h>
#include <stdint.h>
#include <string.h>

static const uint8_t test_key[BEACON_KEY_BYTES] = {
    0x35U, 0x01U, 0x02U, 0x03U, 0x04U, 0x05U, 0x06U,
    0x07U, 0x08U, 0x09U, 0x0aU, 0x0bU, 0x0cU, 0x0dU,
    0x0eU, 0x0fU, 0x10U, 0x11U, 0x12U, 0x13U, 0x14U,
    0x15U, 0x16U, 0x17U, 0x18U, 0x19U, 0x1aU, 0x1bU
};

static void test_address_vector(void)
{
    static const uint8_t expected[BEACON_ADDRESS_BYTES] = {
        0x05U, 0x04U, 0x03U, 0x02U, 0x01U, 0xf5U
    };
    uint8_t address[BEACON_ADDRESS_BYTES];

    assert(beacon_address_from_key(test_key, address) == BEACON_OK);
    assert(memcmp(address, expected, sizeof(address)) == 0);
}

static void test_address_rejects_invalid_static_random_parts(void)
{
    static const uint8_t zero_key[BEACON_KEY_BYTES] = { 0U };
    static const uint8_t one_key[BEACON_KEY_BYTES] = {
        0xffU, 0xffU, 0xffU, 0xffU, 0xffU, 0xffU, 0xffU,
        0xffU, 0xffU, 0xffU, 0xffU, 0xffU, 0xffU, 0xffU,
        0xffU, 0xffU, 0xffU, 0xffU, 0xffU, 0xffU, 0xffU,
        0xffU, 0xffU, 0xffU, 0xffU, 0xffU, 0xffU, 0xffU,
    };
    uint8_t address[BEACON_ADDRESS_BYTES];

    assert(beacon_address_from_key(zero_key, address) ==
           BEACON_ERR_ADDRESS);
    assert(beacon_address_from_key(one_key, address) ==
           BEACON_ERR_ADDRESS);
}

static void test_key_table_validation(void)
{
    static const uint8_t valid_keys[][BEACON_KEY_BYTES] = {
        { 0x35U, 0x01U, 0x02U, 0x03U, 0x04U, 0x05U },
        { 0x36U, 0x01U, 0x02U, 0x03U, 0x04U, 0x05U },
    };
    static const uint8_t invalid_first[][BEACON_KEY_BYTES] = {
        { 0U },
        { 0x36U, 0x01U, 0x02U, 0x03U, 0x04U, 0x05U },
    };
    static const uint8_t invalid_later[][BEACON_KEY_BYTES] = {
        { 0x35U, 0x01U, 0x02U, 0x03U, 0x04U, 0x05U },
        { 0U },
    };

    assert(beacon_key_table_validate(valid_keys, 2U, 2U) == BEACON_OK);
    assert(beacon_key_table_validate(valid_keys, 0U, 2U) ==
           BEACON_ERR_KEY_COUNT);
    assert(beacon_key_table_validate(valid_keys, 2U, 1U) ==
           BEACON_ERR_KEY_COUNT);
    assert(beacon_key_table_validate(invalid_first, 2U, 2U) ==
           BEACON_ERR_ADDRESS);
    assert(beacon_key_table_validate(invalid_later, 2U, 2U) ==
           BEACON_ERR_ADDRESS);
    assert(beacon_key_table_validate(NULL, 1U, 2U) == BEACON_ERR_ARGUMENT);
}

static void test_payload_vector(void)
{
    static const uint8_t expected[BEACON_MANUFACTURER_PAYLOAD_BYTES] = {
        0x4cU, 0x00U, 0x12U, 0x19U, 0x42U, 0x06U, 0x07U,
        0x08U, 0x09U, 0x0aU, 0x0bU, 0x0cU, 0x0dU, 0x0eU,
        0x0fU, 0x10U, 0x11U, 0x12U, 0x13U, 0x14U, 0x15U,
        0x16U, 0x17U, 0x18U, 0x19U, 0x1aU, 0x1bU, 0x00U,
        0x00U
    };
    uint8_t payload[BEACON_MANUFACTURER_PAYLOAD_BYTES];

    assert(beacon_manufacturer_payload_from_key(test_key, payload, 0x42U) ==
           BEACON_OK);
    assert(memcmp(payload, expected, sizeof(payload)) == 0);
}

static void test_ad_vector(void)
{
    static const uint8_t expected[BEACON_AD_BYTES] = {
        0x1eU, 0xffU, 0x4cU, 0x00U, 0x12U, 0x19U, 0x42U,
        0x06U, 0x07U, 0x08U, 0x09U, 0x0aU, 0x0bU, 0x0cU,
        0x0dU, 0x0eU, 0x0fU, 0x10U, 0x11U, 0x12U, 0x13U,
        0x14U, 0x15U, 0x16U, 0x17U, 0x18U, 0x19U, 0x1aU,
        0x1bU, 0x00U, 0x00U
    };
    uint8_t ad[BEACON_AD_BYTES];

    assert(beacon_ad_from_key(test_key, ad, 0x42U) == BEACON_OK);
    assert(memcmp(ad, expected, sizeof(ad)) == 0);
}

static void test_example_key_ad_vector(void)
{
    static const uint8_t key[BEACON_KEY_BYTES] = {
        0xb7U, 0x0eU, 0x0cU, 0xbdU, 0x6bU, 0xb4U, 0xbfU,
        0x7fU, 0x32U, 0x13U, 0x90U, 0xb9U, 0x4aU, 0x03U,
        0xc1U, 0xd3U, 0x56U, 0xc2U, 0x11U, 0x22U, 0x34U,
        0x32U, 0x80U, 0xd6U, 0x11U, 0x5cU, 0x1dU, 0x21U,
    };
    static const uint8_t expected[BEACON_AD_BYTES] = {
        0x1eU, 0xffU, 0x4cU, 0x00U, 0x12U, 0x19U, 0x00U,
        0xbfU, 0x7fU, 0x32U, 0x13U, 0x90U, 0xb9U, 0x4aU,
        0x03U, 0xc1U, 0xd3U, 0x56U, 0xc2U, 0x11U, 0x22U,
        0x34U, 0x32U, 0x80U, 0xd6U, 0x11U, 0x5cU, 0x1dU,
        0x21U, 0x02U, 0x00U,
    };
    uint8_t ad[BEACON_AD_BYTES];

    assert(beacon_ad_from_key(key, ad, 0U) == BEACON_OK);
    assert(memcmp(ad, expected, sizeof(ad)) == 0);
}

static void test_rotation_semantics(void)
{
    struct beacon_rotation_state rotation;
    static const size_t expected_uses[2] = { 0U, 1U };
    size_t uses[2];

    beacon_rotation_init(&rotation);
    assert(rotation.key_index == 0U);
    assert(rotation.cycle == 0U);

    uses[0] = rotation.key_index;
    assert(beacon_rotation_advance(&rotation, 3U, 1U) == BEACON_OK);
    uses[1] = rotation.key_index;
    assert(memcmp(uses, expected_uses, sizeof(uses)) == 0);
    assert(rotation.key_index == 1U);
    assert(rotation.cycle == 0U);

    assert(beacon_rotation_advance(&rotation, 3U, 2U) == BEACON_OK);
    assert(rotation.key_index == 1U);
    assert(rotation.cycle == 1U);
    assert(beacon_rotation_advance(&rotation, 3U, 2U) == BEACON_OK);
    assert(rotation.key_index == 2U);
    assert(rotation.cycle == 0U);

    assert(beacon_rotation_advance(&rotation, 3U, 1U) == BEACON_OK);
    assert(rotation.key_index == 0U);
    assert(rotation.cycle == 0U);
}

static void test_rotation_validation(void)
{
    struct beacon_rotation_state rotation = { 2U, 0U };

    assert(beacon_rotation_advance(NULL, 1U, 1U) == BEACON_ERR_ARGUMENT);
    assert(beacon_rotation_advance(&rotation, 0U, 1U) ==
           BEACON_ERR_KEY_COUNT);
    assert(beacon_rotation_advance(&rotation, 1U, 0U) ==
           BEACON_ERR_REUSE_CYCLES);
    assert(rotation.key_index == 2U);
    assert(rotation.cycle == 0U);
}

static void test_builder_validation(void)
{
    uint8_t address[BEACON_ADDRESS_BYTES];
    uint8_t payload[BEACON_MANUFACTURER_PAYLOAD_BYTES];
    uint8_t ad[BEACON_AD_BYTES];

    assert(beacon_address_from_key(NULL, address) == BEACON_ERR_ARGUMENT);
    assert(beacon_address_from_key(test_key, NULL) == BEACON_ERR_ARGUMENT);
    assert(beacon_manufacturer_payload_from_key(NULL, payload, 0U) ==
           BEACON_ERR_ARGUMENT);
    assert(beacon_manufacturer_payload_from_key(test_key, NULL, 0U) ==
           BEACON_ERR_ARGUMENT);
    assert(beacon_ad_from_key(NULL, ad, 0U) == BEACON_ERR_ARGUMENT);
    assert(beacon_ad_from_key(test_key, NULL, 0U) == BEACON_ERR_ARGUMENT);
}

int main(void)
{
    test_address_vector();
    test_address_rejects_invalid_static_random_parts();
    test_key_table_validation();
    test_payload_vector();
    test_ad_vector();
    test_example_key_ad_vector();
    test_rotation_semantics();
    test_rotation_validation();
    test_builder_validation();
    return 0;
}
