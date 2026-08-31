#include <assert.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>

#ifdef NDEBUG
#error "Host tests require assertions"
#endif

#include "beacon.h"
#include "radio_cycle.h"

enum event_kind {
    EVENT_START,
    EVENT_STOP,
    EVENT_RESET,
    EVENT_SLEEP
};

struct event {
    enum event_kind kind;
    uint32_t value;
};

struct fake_radio {
    int start_result;
    int stop_results[2];
    int reset_result;
    size_t stop_count;
    struct event events[5];
    size_t event_count;
};

static void record_event(struct fake_radio *radio, enum event_kind kind,
                         uint32_t value)
{
    radio->events[radio->event_count] =
        (struct event){ .kind = kind, .value = value };
    radio->event_count += 1U;
}

static int fake_start(void *context, size_t key_index, uint16_t interval_units)
{
    struct fake_radio *radio = context;

    record_event(radio, EVENT_START, (uint32_t)key_index);
    assert(interval_units == 8000U);
    return radio->start_result;
}

static int fake_stop(void *context)
{
    struct fake_radio *radio = context;
    const size_t result_index = radio->stop_count;

    record_event(radio, EVENT_STOP, 0U);
    radio->stop_count += 1U;
    return radio->stop_results[result_index];
}

static int fake_reset(void *context, size_t next_key_index)
{
    struct fake_radio *radio = context;

    record_event(radio, EVENT_RESET, (uint32_t)next_key_index);
    return radio->reset_result;
}

static void fake_sleep(void *context, uint32_t seconds)
{
    record_event(context, EVENT_SLEEP, seconds);
}

static struct radio_cycle_config test_config(void)
{
    return (struct radio_cycle_config){
        .key_count = 2U,
        .reuse_cycles = 1U,
        .advertise_seconds = 1800U,
        .sleep_seconds = 0U,
        .interval_units = 8000U,
    };
}

static struct radio_cycle_ops test_ops(struct fake_radio *radio)
{
    return (struct radio_cycle_ops){
        .start = fake_start,
        .stop = fake_stop,
        .reset = fake_reset,
        .sleep = fake_sleep,
        .context = radio,
    };
}

static void test_run_once_orders_success(void)
{
    struct beacon_rotation_state rotation;
    struct fake_radio radio = { 0 };
    const struct radio_cycle_config config = test_config();
    const struct radio_cycle_ops ops = test_ops(&radio);

    beacon_rotation_init(&rotation);

    assert(radio_cycle_run_once(&rotation, &config, &ops) == 0);
    assert(radio.event_count == 5U);
    assert(radio.events[0].kind == EVENT_START && radio.events[0].value == 0U);
    assert(radio.events[1].kind == EVENT_SLEEP &&
           radio.events[1].value == 1800U);
    assert(radio.events[2].kind == EVENT_STOP);
    assert(radio.events[3].kind == EVENT_RESET && radio.events[3].value == 1U);
    assert(radio.events[4].kind == EVENT_SLEEP && radio.events[4].value == 0U);
    assert(rotation.key_index == 1U);
    assert(rotation.cycle == 0U);
}

static void test_run_once_retries_stop_once_and_preserves_error(void)
{
    struct beacon_rotation_state rotation;
    struct fake_radio radio = { .stop_results = { -EIO, -EPERM } };
    const struct radio_cycle_config config = test_config();
    const struct radio_cycle_ops ops = test_ops(&radio);

    beacon_rotation_init(&rotation);

    assert(radio_cycle_run_once(&rotation, &config, &ops) == -EIO);
    assert(radio.event_count == 4U);
    assert(radio.events[0].kind == EVENT_START);
    assert(radio.events[1].kind == EVENT_SLEEP &&
           radio.events[1].value == 1800U);
    assert(radio.events[2].kind == EVENT_STOP);
    assert(radio.events[3].kind == EVENT_STOP);
    assert(radio.stop_count == 2U);
    assert(rotation.key_index == 0U);
    assert(rotation.cycle == 0U);
}

static void test_run_once_returns_start_error(void)
{
    struct beacon_rotation_state rotation;
    struct fake_radio radio = { .start_result = -EACCES };
    const struct radio_cycle_config config = test_config();
    const struct radio_cycle_ops ops = test_ops(&radio);

    beacon_rotation_init(&rotation);

    assert(radio_cycle_run_once(&rotation, &config, &ops) == -EACCES);
    assert(radio.event_count == 1U);
    assert(radio.events[0].kind == EVENT_START);
    assert(rotation.key_index == 0U);
    assert(rotation.cycle == 0U);
}

static void test_run_once_returns_reset_error(void)
{
    struct beacon_rotation_state rotation;
    struct fake_radio radio = { .reset_result = -EPERM };
    const struct radio_cycle_config config = test_config();
    const struct radio_cycle_ops ops = test_ops(&radio);

    beacon_rotation_init(&rotation);

    assert(radio_cycle_run_once(&rotation, &config, &ops) == -EPERM);
    assert(radio.event_count == 4U);
    assert(radio.events[0].kind == EVENT_START);
    assert(radio.events[1].kind == EVENT_SLEEP &&
           radio.events[1].value == 1800U);
    assert(radio.events[2].kind == EVENT_STOP);
    assert(radio.events[3].kind == EVENT_RESET && radio.events[3].value == 1U);
    assert(rotation.key_index == 1U);
    assert(rotation.cycle == 0U);
}

static void test_run_once_rejects_invalid_arguments(void)
{
    struct beacon_rotation_state rotation;
    struct fake_radio radio = { 0 };
    struct radio_cycle_config config = test_config();
    struct radio_cycle_ops ops = test_ops(&radio);

    beacon_rotation_init(&rotation);

    assert(radio_cycle_run_once(NULL, &config, &ops) == -EINVAL);
    assert(radio_cycle_run_once(&rotation, NULL, &ops) == -EINVAL);
    assert(radio_cycle_run_once(&rotation, &config, NULL) == -EINVAL);
    config.key_count = 0U;
    assert(radio_cycle_run_once(&rotation, &config, &ops) == -EINVAL);
    config = test_config();
    config.reuse_cycles = 0U;
    assert(radio_cycle_run_once(&rotation, &config, &ops) == -EINVAL);
    config = test_config();
    config.interval_units = 0U;
    assert(radio_cycle_run_once(&rotation, &config, &ops) == -EINVAL);
    config = test_config();
    ops.start = NULL;
    assert(radio_cycle_run_once(&rotation, &config, &ops) == -EINVAL);
    ops = test_ops(&radio);
    ops.reset = NULL;
    assert(radio_cycle_run_once(&rotation, &config, &ops) == -EINVAL);
    ops = test_ops(&radio);
    ops.sleep = NULL;
    assert(radio_cycle_run_once(&rotation, &config, &ops) == -EINVAL);
    ops = test_ops(&radio);
    rotation.key_index = config.key_count;
    assert(radio_cycle_run_once(&rotation, &config, &ops) == -EINVAL);
    ops.stop = NULL;
    assert(radio_cycle_run_once(&rotation, &config, &ops) == -EINVAL);
}

int main(void)
{
    test_run_once_orders_success();
    test_run_once_retries_stop_once_and_preserves_error();
    test_run_once_returns_start_error();
    test_run_once_returns_reset_error();
    test_run_once_rejects_invalid_arguments();
    return 0;
}
