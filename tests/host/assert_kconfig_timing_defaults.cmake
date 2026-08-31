file(READ "${KCONFIG_FILE}" kconfig)

function(assert_default symbol expected)
    string(FIND "${kconfig}" "config ${symbol}\n" stanza_start)
    if(stanza_start EQUAL -1)
        message(FATAL_ERROR "Missing ${symbol}")
    endif()

    string(SUBSTRING "${kconfig}" ${stanza_start} -1 stanza)
    string(FIND "${stanza}" "\nconfig " next_config)
    if(NOT next_config EQUAL -1)
        string(SUBSTRING "${stanza}" 0 ${next_config} stanza)
    endif()

    string(FIND "${stanza}" "\n\tdefault ${expected}\n" default_start)
    if(default_start EQUAL -1)
        message(FATAL_ERROR "${symbol} must default to ${expected}")
    endif()
endfunction()

assert_default(REUSE_CYCLES 1)
assert_default(ADVERTISE_WINDOW_S 1800)
assert_default(SLEEP_S 0)
assert_default(ADV_INTERVAL_MS 5000)
