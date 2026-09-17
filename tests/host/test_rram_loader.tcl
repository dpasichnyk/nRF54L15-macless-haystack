proc check {condition message} {
    if {![uplevel 1 [list expr $condition]]} { error $message }
}

proc mww {address value} { lappend ::writes [list $address $value] }
proc load_image {file} { lappend ::writes [list load $file] }
proc read_memory {address width count} {
    check {$address == 0x5004b418 && $width == 32 && $count == 1} "wrong status read"
    incr ::polls
    return [list [expr {$::polls >= $::ready_after}]]
}
proc sleep {milliseconds} {
    check {$milliseconds == 1} "unexpected poll delay"
    incr ::sleeps
}

source [lindex $argv 0]

set writes {}
set polls 0
set sleeps 0
set ready_after 3
nrf54l-load fixture.hex
check {$polls == 3 && $sleeps == 2} "did not wait for buffer completion"
check {$writes eq {{0x5004b500 0x101} {load fixture.hex} {0x5004b008 1} {0x5004b500 0}}} "write/commit/disable order changed"

set writes {}
set polls 0
set sleeps 0
set ready_after 101
check {[catch {nrf54l-load fixture.hex}] == 1} "timeout was swallowed"
check {$polls == 100 && $sleeps == 100} "timeout is not bounded"
check {[llength $writes] == 3} "loader continued after failed commit"

proc load_image {file} { error "injected load failure" }
set writes {}
check {[catch {nrf54l-load fixture.hex} result] == 1} "load failure was swallowed"
check {$result eq "injected load failure"} "load error was changed"
check {[llength $writes] == 1} "loader committed after failed load"
puts "RRAM load/commit ordering, timeout and load failure passed"
