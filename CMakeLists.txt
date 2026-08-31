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

if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/src/keys.c)
  target_sources(app PRIVATE src/keys.c)
elseif(BEACON_ALLOW_EXAMPLE_KEYS)
  target_sources(app PRIVATE src/keys.example.c)
else()
  message(FATAL_ERROR
    "Missing src/keys.c. Generate it with scripts/keys_csv_to_c.py, or set "
    "BEACON_ALLOW_EXAMPLE_KEYS=ON for a nonfunctional development build.")
endif()
