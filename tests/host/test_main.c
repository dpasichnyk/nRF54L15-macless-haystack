#include <assert.h>
#include <errno.h>
#include <stdint.h>

#include <ram_pwrdn.h>

#define main firmware_main
#include "../../src/main.c"
#undef main

char _image_ram_end[1];
static unsigned int power_down_calls;
static unsigned int reboot_calls;
static int radio_result;

void power_down_ram(uintptr_t start_address, uintptr_t end_address)
{
    assert(start_address == (uintptr_t)_image_ram_end);
    assert(end_address == 0x2002f000UL);
    power_down_calls += 1U;
}

int radio_zephyr_run(void)
{
#if defined(CONFIG_RAM_POWER_DOWN_LIBRARY)
    assert(power_down_calls == 1U);
#else
    assert(power_down_calls == 0U);
#endif
    return radio_result;
}

void sys_reboot(int type)
{
    assert(type == SYS_REBOOT_COLD);
    reboot_calls += 1U;
}

int main(void)
{
    radio_result = 0;
    assert(firmware_main() == 0);
    assert(reboot_calls == 0U);

    power_down_calls = 0U;
    radio_result = -EIO;
    assert(firmware_main() == 0);
    assert(reboot_calls == 1U);
    return 0;
}
