#ifndef ZEPHYR_SYS_UTIL_H
#define ZEPHYR_SYS_UTIL_H

#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))
#define BUILD_ASSERT(condition, message) _Static_assert(condition, message)

#endif
