#include "radio_zephyr.h"

#include <errno.h>
#include <stdint.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/util.h>

#include "beacon.h"
#include "keys.h"
#include "radio_cycle.h"

LOG_MODULE_REGISTER(radio_zephyr);

#define RADIO_DEDICATED_ID 1U
#define RADIO_ADV_INTERVAL_MIN 0x0020U
#define RADIO_ADV_INTERVAL_MAX 0x4000U
#define RADIO_ADV_INTERVAL_UNITS \
    ((uint16_t)(((uint64_t)CONFIG_ADV_INTERVAL_MS * 8U) / 5U))

BUILD_ASSERT(CONFIG_ADV_INTERVAL_MS > 0,
             "CONFIG_ADV_INTERVAL_MS must be positive");
BUILD_ASSERT((CONFIG_ADV_INTERVAL_MS % 5U) == 0U,
             "CONFIG_ADV_INTERVAL_MS must be a multiple of 5");
BUILD_ASSERT(((uint64_t)CONFIG_ADV_INTERVAL_MS * 8U) / 5U >=
                 RADIO_ADV_INTERVAL_MIN,
             "CONFIG_ADV_INTERVAL_MS is below the legacy advertising minimum");
BUILD_ASSERT(((uint64_t)CONFIG_ADV_INTERVAL_MS * 8U) / 5U <=
                 RADIO_ADV_INTERVAL_MAX,
             "CONFIG_ADV_INTERVAL_MS exceeds the legacy advertising maximum");

static int identity_address_from_key(
    const uint8_t key[BEACON_KEY_BYTES], bt_addr_le_t *address)
{
    int error;

    address->type = BT_ADDR_LE_RANDOM;
    error = beacon_address_from_key(key, address->a.val);
    if (error != BEACON_OK) {
        LOG_ERR("Could not derive identity address: %d", error);
        return -EINVAL;
    }

    return 0;
}

static int reset_identity(uint8_t dedicated_id,
                          const uint8_t key[BEACON_KEY_BYTES])
{
    bt_addr_le_t address;
    int error;

    error = identity_address_from_key(key, &address);
    if (error != 0) {
        return error;
    }

    error = bt_id_reset(dedicated_id, &address, NULL);
    if (error != 0) {
        LOG_ERR("Could not reset identity %u: %d", (unsigned int)dedicated_id,
                error);
    }

    return error;
}

struct radio_zephyr_context {
    uint8_t dedicated_id;
};

static int start_advertising(void *context, size_t key_index,
                             uint16_t interval_units)
{
    const struct radio_zephyr_context *radio = context;
    uint8_t payload[BEACON_MANUFACTURER_PAYLOAD_BYTES];
    const struct bt_data ad[] = {
        BT_DATA(BT_DATA_MANUFACTURER_DATA, payload, sizeof(payload)),
    };
    const struct bt_le_adv_param parameters = {
        .id = radio->dedicated_id,
        .options = BT_LE_ADV_OPT_USE_IDENTITY,
        .interval_min = interval_units,
        .interval_max = interval_units,
    };
    int error;

    error = beacon_manufacturer_payload_from_key(beacon_keys[key_index], payload,
                                                 CONFIG_STATE_BYTE);
    if (error != BEACON_OK) {
        LOG_ERR("Could not construct advertisement payload: %d", error);
        return -EINVAL;
    }

    error = bt_le_adv_start(&parameters, ad, ARRAY_SIZE(ad), NULL, 0U);
    if (error != 0) {
        LOG_ERR("Could not start advertising: %d", error);
        return error;
    }

    LOG_INF("Advertising key %u", (unsigned int)key_index);
    return 0;
}

static int stop_advertising(void *context)
{
    int error;

    (void)context;
    error = bt_le_adv_stop();
    if (error != 0) {
        LOG_ERR("Could not stop advertising: %d", error);
    }
    return error;
}

static int reset_advertising_identity(void *context, size_t next_key_index)
{
    const struct radio_zephyr_context *radio = context;

    return reset_identity(radio->dedicated_id, beacon_keys[next_key_index]);
}

static void sleep_seconds(void *context, uint32_t seconds)
{
    (void)context;
    k_sleep(K_SECONDS(seconds));
}

int radio_zephyr_run(void)
{
    struct beacon_rotation_state rotation;
    struct radio_zephyr_context radio;
    const struct radio_cycle_config config = {
        .key_count = beacon_key_count,
        .reuse_cycles = CONFIG_REUSE_CYCLES,
        .advertise_seconds = CONFIG_ADVERTISE_WINDOW_S,
        .sleep_seconds = CONFIG_SLEEP_S,
        .interval_units = RADIO_ADV_INTERVAL_UNITS,
    };
    const struct radio_cycle_ops ops = {
        .start = start_advertising,
        .stop = stop_advertising,
        .reset = reset_advertising_identity,
        .sleep = sleep_seconds,
        .context = &radio,
    };
    uint8_t dedicated_id;
    int error;

    error = beacon_key_table_validate(beacon_keys, beacon_key_count,
                                      CONFIG_N_KEYS);
    if (error != BEACON_OK) {
        LOG_ERR("Invalid beacon key table: %d", error);
        return -EINVAL;
    }

    beacon_rotation_init(&rotation);

    error = bt_enable(NULL);
    if (error != 0) {
        LOG_ERR("Bluetooth initialization failed: %d", error);
        return error;
    }

    bt_addr_le_t address;
    error = identity_address_from_key(beacon_keys[rotation.key_index], &address);
    if (error != 0) {
        return error;
    }

    error = bt_id_create(&address, NULL);
    if (error < 0) {
        LOG_ERR("Could not create dedicated identity: %d", error);
        return error;
    }

    dedicated_id = (uint8_t)error;
    if (dedicated_id != RADIO_DEDICATED_ID) {
        LOG_ERR("Dedicated identity is %u, expected %u", (unsigned int)dedicated_id,
                RADIO_DEDICATED_ID);
        return -EIO;
    }

    LOG_INF("Bluetooth enabled with dedicated identity %u",
            (unsigned int)dedicated_id);
    radio.dedicated_id = dedicated_id;

    for (;;) {
        error = radio_cycle_run_once(&rotation, &config, &ops);
        if (error != 0) {
            LOG_ERR("Radio lifecycle failed: %d", error);
            return error;
        }
    }
}
