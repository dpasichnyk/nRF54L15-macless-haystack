#include "radio_zephyr.h"

#include <zephyr/sys/reboot.h>

int main(void)
{
    if (radio_zephyr_run() != 0) {
        sys_reboot(SYS_REBOOT_COLD);
    }

    return 0;
}
