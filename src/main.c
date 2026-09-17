#include "radio_zephyr.h"

#include <zephyr/sys/reboot.h>

#if defined(CONFIG_RAM_POWER_DOWN_LIBRARY)
#include <stdint.h>
#include <ram_pwrdn.h>
#include <zephyr/devicetree.h>
#include <zephyr/sys/util.h>

extern char _image_ram_end[];

BUILD_ASSERT(CONFIG_COMMON_LIBC_MALLOC_ARENA_SIZE == 0,
             "RAM power-down requires the post-image libc heap to be disabled");
BUILD_ASSERT(CONFIG_NRF_FORCE_RAM_ON_REBOOT,
             "RAM must be restored before a software reboot");
#endif

int main(void)
{
#if defined(CONFIG_RAM_POWER_DOWN_LIBRARY)
    /* Stay within CPUAPP RAM; the unused-RAM helper also reaches FLPR memory. */
    power_down_ram((uintptr_t)_image_ram_end,
                   DT_REG_ADDR(DT_CHOSEN(zephyr_sram)) +
                       DT_REG_SIZE(DT_CHOSEN(zephyr_sram)));
#endif
    if (radio_zephyr_run() != 0) {
        sys_reboot(SYS_REBOOT_COLD);
    }

    return 0;
}
