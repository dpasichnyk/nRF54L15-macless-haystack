#ifndef ZEPHYR_KERNEL_H
#define ZEPHYR_KERNEL_H

#include <stdint.h>

#define K_SECONDS(seconds) (seconds)

void k_sleep(uint32_t timeout);

#endif
