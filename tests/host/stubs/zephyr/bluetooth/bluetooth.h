#ifndef ZEPHYR_BLUETOOTH_BLUETOOTH_H
#define ZEPHYR_BLUETOOTH_BLUETOOTH_H

#include <stddef.h>
#include <stdint.h>

#define BT_ADDR_LE_RANDOM 1U
#define BT_DATA_MANUFACTURER_DATA 0xffU
#define BT_LE_ADV_OPT_USE_IDENTITY 1U

typedef struct {
    uint8_t val[6];
} bt_addr_t;

typedef struct {
    uint8_t type;
    bt_addr_t a;
} bt_addr_le_t;

struct bt_data {
    uint8_t type;
    const uint8_t *data;
    uint8_t data_len;
};

struct bt_le_adv_param {
    uint8_t id;
    uint32_t options;
    uint16_t interval_min;
    uint16_t interval_max;
};

#define BT_DATA(_type, _data, _data_len) \
    { .type = (_type), .data = (_data), .data_len = (_data_len) }

typedef void (*bt_ready_cb_t)(int error);

int bt_enable(bt_ready_cb_t callback);
int bt_id_create(bt_addr_le_t *addr, uint8_t *irk);
int bt_id_reset(uint8_t id, bt_addr_le_t *addr, uint8_t *irk);
int bt_le_adv_start(const struct bt_le_adv_param *param,
                    const struct bt_data *ad, size_t ad_len,
                    const struct bt_data *sd, size_t sd_len);
int bt_le_adv_stop(void);

#endif
