#ifndef KEYS_H
#define KEYS_H

#include <stddef.h>
#include <stdint.h>

#include "beacon.h"

extern const uint8_t beacon_keys[][BEACON_KEY_BYTES];
extern const size_t beacon_key_count;

#endif
