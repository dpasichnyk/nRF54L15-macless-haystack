cmake_minimum_required(VERSION 3.20)

if(NOT PROFILE STREQUAL "production" AND NOT PROFILE STREQUAL "development")
  message(FATAL_ERROR "PROFILE must be production or development")
endif()

file(STRINGS "${BUILD_DIR}/zephyr/.config" config)

set(enabled BT BT_BROADCASTER HW_STACK_PROTECTION TICKLESS_KERNEL)
set(disabled SERIAL UART_CONSOLE BT_CENTRAL BT_PERIPHERAL BT_OBSERVER BT_EXT_ADV BT_SETTINGS)
set(settings BT_ID_MAX=2 ADV_INTERVAL_MS=5000 ADVERTISE_WINDOW_S=1800 SLEEP_S=0)
if(PROFILE STREQUAL "production")
  list(APPEND enabled SIZE_OPTIMIZATIONS RAM_POWER_DOWN_LIBRARY NRF_FORCE_RAM_ON_REBOOT)
  list(APPEND settings COMMON_LIBC_MALLOC_ARENA_SIZE=0)
  list(APPEND disabled CONSOLE LOG PRINTK USE_SEGGER_RTT)
else()
  list(APPEND disabled RAM_POWER_DOWN_LIBRARY)
  list(APPEND settings COMMON_LIBC_MALLOC_ARENA_SIZE=-1)
  list(APPEND enabled ASSERT DEBUG_OPTIMIZATIONS LOG LOG_BACKEND_RTT
       LOG_BACKEND_RTT_MODE_DROP USE_SEGGER_RTT RTT_CONSOLE CONSOLE PRINTK
       NCS_BOOT_BANNER LOG_MODE_DEFERRED)
  list(APPEND settings SEGGER_RTT_BUFFER_SIZE_UP=4096 LOG_BACKEND_RTT_MESSAGE_SIZE=256)
endif()

foreach(symbol IN LISTS enabled)
  if(NOT "CONFIG_${symbol}=y" IN_LIST config)
    message(FATAL_ERROR "${PROFILE}: CONFIG_${symbol} must be enabled")
  endif()
endforeach()
foreach(symbol IN LISTS disabled)
  if("CONFIG_${symbol}=y" IN_LIST config)
    message(FATAL_ERROR "${PROFILE}: CONFIG_${symbol} must be disabled")
  endif()
endforeach()

foreach(setting IN LISTS settings)
  if(NOT "CONFIG_${setting}" IN_LIST config)
    message(FATAL_ERROR "${PROFILE}: expected CONFIG_${setting}")
  endif()
endforeach()

message(STATUS "${PROFILE} configuration verified")
