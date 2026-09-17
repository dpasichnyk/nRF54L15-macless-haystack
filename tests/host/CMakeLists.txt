cmake_minimum_required(VERSION 3.16)

project(beacon_host_tests LANGUAGES C)

add_executable(test_beacon
    test_beacon.c
    ../../src/beacon.c
)
target_include_directories(test_beacon PRIVATE ../../include)
target_compile_features(test_beacon PRIVATE c_std_11)
target_compile_options(test_beacon PRIVATE -UNDEBUG)

add_executable(test_radio_cycle
    test_radio_cycle.c
    ../../src/beacon.c
    ../../src/radio_cycle.c
)
target_include_directories(test_radio_cycle PRIVATE ../../include)
target_compile_features(test_radio_cycle PRIVATE c_std_11)
target_compile_options(test_radio_cycle PRIVATE -UNDEBUG)

add_executable(test_radio_zephyr_adapter
    test_radio_zephyr_adapter.c
    ../../src/beacon.c
    ../../src/radio_cycle.c
    ../../src/radio_zephyr.c
)
target_include_directories(test_radio_zephyr_adapter PRIVATE
    stubs
    ../../include
)
target_compile_definitions(test_radio_zephyr_adapter PRIVATE
    CONFIG_ADV_INTERVAL_MS=5000
    CONFIG_ADVERTISE_WINDOW_S=1800
    CONFIG_N_KEYS=2
    CONFIG_REUSE_CYCLES=1
    CONFIG_SLEEP_S=0
    CONFIG_STATE_BYTE=0
)
target_compile_features(test_radio_zephyr_adapter PRIVATE c_std_11)
target_compile_options(test_radio_zephyr_adapter PRIVATE -UNDEBUG)

add_executable(test_radio_zephyr_reuse_adapter
    test_radio_zephyr_reuse_adapter.c
    ../../src/beacon.c
    ../../src/radio_cycle.c
    ../../src/radio_zephyr.c
)
target_include_directories(test_radio_zephyr_reuse_adapter PRIVATE
    stubs
    ../../include
)
target_compile_definitions(test_radio_zephyr_reuse_adapter PRIVATE
    CONFIG_ADV_INTERVAL_MS=5000
    CONFIG_ADVERTISE_WINDOW_S=1800
    CONFIG_N_KEYS=1
    CONFIG_REUSE_CYCLES=2
    CONFIG_SLEEP_S=0
    CONFIG_STATE_BYTE=0
)
target_compile_features(test_radio_zephyr_reuse_adapter PRIVATE c_std_11)
target_compile_options(test_radio_zephyr_reuse_adapter PRIVATE -UNDEBUG)

enable_testing()
foreach(profile production development)
    add_executable(test_main_${profile} test_main.c)
    target_include_directories(test_main_${profile} PRIVATE stubs ../../include)
    target_compile_features(test_main_${profile} PRIVATE c_std_11)
    target_compile_options(test_main_${profile} PRIVATE -UNDEBUG)
    add_test(NAME main_${profile}_host COMMAND test_main_${profile})
endforeach()
target_compile_definitions(test_main_production PRIVATE
    CONFIG_RAM_POWER_DOWN_LIBRARY=1
    CONFIG_COMMON_LIBC_MALLOC_ARENA_SIZE=0
    CONFIG_NRF_FORCE_RAM_ON_REBOOT=1
)
find_program(TCLSH NAMES tclsh REQUIRED)
add_test(NAME rram_loader_host COMMAND ${TCLSH}
    ${CMAKE_CURRENT_SOURCE_DIR}/test_rram_loader.tcl
    ${CMAKE_CURRENT_SOURCE_DIR}/../../scripts/openocd-rram.cfg)
add_test(NAME beacon_host COMMAND test_beacon)
add_test(NAME radio_cycle_host COMMAND test_radio_cycle)
add_test(NAME radio_zephyr_adapter_host COMMAND test_radio_zephyr_adapter)
add_test(NAME radio_zephyr_reuse_adapter_host COMMAND test_radio_zephyr_reuse_adapter)
add_test(
    NAME kconfig_timing_defaults
    COMMAND ${CMAKE_COMMAND}
        -DKCONFIG_FILE=${CMAKE_CURRENT_SOURCE_DIR}/../../Kconfig
        -P ${CMAKE_CURRENT_SOURCE_DIR}/assert_kconfig_timing_defaults.cmake
)
