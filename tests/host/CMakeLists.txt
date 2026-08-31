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

enable_testing()
add_test(NAME beacon_host COMMAND test_beacon)
add_test(NAME radio_cycle_host COMMAND test_radio_cycle)
add_test(
    NAME kconfig_timing_defaults
    COMMAND ${CMAKE_COMMAND}
        -DKCONFIG_FILE=${CMAKE_CURRENT_SOURCE_DIR}/../../Kconfig
        -P ${CMAKE_CURRENT_SOURCE_DIR}/assert_kconfig_timing_defaults.cmake
)
