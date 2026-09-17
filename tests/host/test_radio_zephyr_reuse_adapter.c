#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/bluetooth/bluetooth.h>

#include "beacon.h"
#include "keys.h"
#include "radio_zephyr.h"

const uint8_t beacon_keys[][BEACON_KEY_BYTES] = {
    { 0x35U, 0x01U, 0x02U, 0x03U, 0x04U, 0x05U, 0x10U },
};
const size_t beacon_key_count = sizeof(beacon_keys) / sizeof(beacon_keys[0]);

static bool advertising_active;
static size_t advertising_start_count;
static size_t advertising_stop_count;
static size_t identity_reset_count;
static uint8_t identity_address[BEACON_ADDRESS_BYTES];

int bt_enable(bt_ready_cb_t callback)
{
    assert(callback == NULL);
    return 0;
}

int bt_id_create(bt_addr_le_t *address, uint8_t *irk)
{
    assert(address->type == BT_ADDR_LE_RANDOM);
    assert(irk == NULL);
    memcpy(identity_address, address->a.val, sizeof(identity_address));
    return 1;
}

int bt_id_reset(uint8_t id, bt_addr_le_t *address, uint8_t *irk)
{
    assert(id == 1U);
    assert(!advertising_active);
    assert(irk == NULL);
    identity_reset_count += 1U;
    if (address->type == BT_ADDR_LE_RANDOM &&
        memcmp(address->a.val, identity_address, sizeof(identity_address)) == 0) {
        return -EALREADY;
    }

    return 1;
}

int bt_le_adv_start(const struct bt_le_adv_param *parameters,
                    const struct bt_data *ad, size_t ad_len,
                    const struct bt_data *sd, size_t sd_len)
{
    assert(parameters->id == 1U);
    assert(parameters->interval_min == 8000U);
    assert(parameters->interval_max == 8000U);
    assert(ad_len == 1U);
    assert(ad[0].data_len == BEACON_MANUFACTURER_PAYLOAD_BYTES);
    assert(sd == NULL);
    assert(sd_len == 0U);
    assert(!advertising_active);
    advertising_start_count += 1U;
    if (advertising_start_count == 2U) {
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
    assert(radio_zephyr_run() == -EINTR);
    assert(advertising_start_count == 2U);
    assert(advertising_stop_count == 1U);
    assert(identity_reset_count == 0U);
    assert(!advertising_active);
    return 0;
}
