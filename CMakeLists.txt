cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(nrf5_tag)

target_include_directories(app PRIVATE include)

target_sources(app PRIVATE
  src/main.c
  src/radio_zephyr.c
  src/radio_cycle.c
  src/beacon.c
)

option(BEACON_ALLOW_EXAMPLE_KEYS "Build with the nonfunctional example key" OFF)

set(BEACON_KEYS_C "${CMAKE_CURRENT_SOURCE_DIR}/src/keys.c" CACHE FILEPATH
    "Generated public key table compiled into the firmware")

if(EXISTS ${BEACON_KEYS_C})
  target_sources(app PRIVATE ${BEACON_KEYS_C})
elseif(BEACON_ALLOW_EXAMPLE_KEYS)
  target_sources(app PRIVATE src/keys.example.c)
else()
  message(FATAL_ERROR
    "Missing ${BEACON_KEYS_C}. Generate it with scripts/keys_csv_to_c.py, or set "
    "BEACON_ALLOW_EXAMPLE_KEYS=ON for a nonfunctional development build.")
endif()
