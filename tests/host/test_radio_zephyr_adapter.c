#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/bluetooth/bluetooth.h>

#include "beacon.h"
#include "keys.h"
#include "radio_zephyr.h"

const uint8_t beacon_keys[][BEACON_KEY_BYTES] = {
    { 0x35U, 0x01U, 0x02U, 0x03U, 0x04U, 0x05U, 0x10U },
    { 0x36U, 0x11U, 0x12U, 0x13U, 0x14U, 0x15U, 0x20U },
};
const size_t beacon_key_count = sizeof(beacon_keys) / sizeof(beacon_keys[0]);

static size_t advertising_start_count;
static size_t advertising_stop_count;
static size_t identity_reset_count;
static size_t identity_create_count;
static bool advertising_active;
static int identity_reset_result;
static int identity_create_result = 1;
static uint8_t created_address[BEACON_ADDRESS_BYTES];
static uint8_t reset_addresses[2][BEACON_ADDRESS_BYTES];
static uint8_t advertised_payloads[3][BEACON_MANUFACTURER_PAYLOAD_BYTES];

int bt_enable(bt_ready_cb_t callback)
{
    assert(callback == NULL);
    return 0;
}

int bt_id_create(bt_addr_le_t *address, uint8_t *irk)
{
    assert(address->type == BT_ADDR_LE_RANDOM);
    assert(irk == NULL);
    assert(identity_create_count == 0U);
    memcpy(created_address, address->a.val, sizeof(created_address));
    identity_create_count += 1U;
    return identity_create_result;
}

int bt_id_reset(uint8_t id, bt_addr_le_t *address, uint8_t *irk)
{
    assert(id == 1U);
    assert(address->type == BT_ADDR_LE_RANDOM);
    assert(irk == NULL);
    assert(!advertising_active);
    assert(identity_reset_count < sizeof(reset_addresses) / sizeof(reset_addresses[0]));
    memcpy(reset_addresses[identity_reset_count], address->a.val,
           sizeof(reset_addresses[0]));
    identity_reset_count += 1U;
    return identity_reset_result;
}

int bt_le_adv_start(const struct bt_le_adv_param *parameters,
                    const struct bt_data *ad, size_t ad_len,
                    const struct bt_data *sd, size_t sd_len)
{
    assert(parameters->id == 1U);
    assert(parameters->options == BT_LE_ADV_OPT_USE_IDENTITY);
    assert(parameters->interval_min == 8000U);
    assert(parameters->interval_max == 8000U);
    assert(ad_len == 1U);
    assert(ad[0].type == BT_DATA_MANUFACTURER_DATA);
    assert(ad[0].data_len == BEACON_MANUFACTURER_PAYLOAD_BYTES);
    assert(sd == NULL);
    assert(sd_len == 0U);

    assert(!advertising_active);
    assert(advertising_start_count <
           sizeof(advertised_payloads) / sizeof(advertised_payloads[0]));
    memcpy(advertised_payloads[advertising_start_count], ad[0].data,
           sizeof(advertised_payloads[0]));
    advertising_start_count += 1U;
    if (advertising_start_count == 3U) {
        return -EINTR;
    }

    advertising_active = true;
    return 0;
}

int bt_le_adv_stop(void)
{
    assert(advertising_active);
    advertising_stop_count += 1U;
    advertising_active = false;
    return 0;
}

void k_sleep(uint32_t timeout)
{
    (void)timeout;
}

int main(void)
{
    uint8_t expected_address[BEACON_ADDRESS_BYTES];
    uint8_t expected_payload[BEACON_MANUFACTURER_PAYLOAD_BYTES];

    identity_reset_result = 1;
    assert(radio_zephyr_run() == -EINTR);
    assert(advertising_start_count == 3U);
    assert(advertising_stop_count == 2U);
    assert(identity_reset_count == 2U);
    assert(identity_create_count == 1U);
    assert(!advertising_active);

    assert(beacon_address_from_key(beacon_keys[0], expected_address) == BEACON_OK);
    assert(memcmp(created_address, expected_address, sizeof(created_address)) == 0);
    assert(beacon_address_from_key(beacon_keys[1], expected_address) == BEACON_OK);
    assert(memcmp(reset_addresses[0], expected_address,
                  sizeof(reset_addresses[0])) == 0);
    assert(beacon_address_from_key(beacon_keys[0], expected_address) == BEACON_OK);
    assert(memcmp(reset_addresses[1], expected_address,
                  sizeof(reset_addresses[1])) == 0);

    assert(beacon_manufacturer_payload_from_key(beacon_keys[0], expected_payload,
                                                0U) == BEACON_OK);
    assert(memcmp(advertised_payloads[0], expected_payload,
                  sizeof(expected_payload)) == 0);
    assert(beacon_manufacturer_payload_from_key(beacon_keys[1], expected_payload,
                                                0U) == BEACON_OK);
    assert(memcmp(advertised_payloads[1], expected_payload,
                  sizeof(expected_payload)) == 0);
    assert(beacon_manufacturer_payload_from_key(beacon_keys[0], expected_payload,
                                                0U) == BEACON_OK);
    assert(memcmp(advertised_payloads[2], expected_payload,
                  sizeof(expected_payload)) == 0);

    advertising_start_count = 0U;
    advertising_stop_count = 0U;
    identity_reset_count = 0U;
    identity_create_count = 0U;
    advertising_active = false;
    identity_reset_result = -EIO;
    assert(radio_zephyr_run() == -EIO);
    assert(advertising_start_count == 1U);
    assert(advertising_stop_count == 1U);
    assert(identity_reset_count == 1U);
    assert(!advertising_active);

    const int create_results[] = { -ENOMEM, 0 };
    for (size_t i = 0U; i < sizeof(create_results) / sizeof(create_results[0]); ++i) {
        advertising_start_count = 0U;
        advertising_stop_count = 0U;
        identity_reset_count = 0U;
        identity_create_count = 0U;
        identity_create_result = create_results[i];
        const int expected = create_results[i] < 0 ? create_results[i] : -EIO;

        assert(radio_zephyr_run() == expected);
        assert(identity_create_count == 1U);
        assert(advertising_start_count == 0U);
        assert(advertising_stop_count == 0U);
        assert(identity_reset_count == 0U);
    }
    return 0;
}
