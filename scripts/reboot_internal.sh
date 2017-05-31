#!/bin/bash
# Tell internal unit to reboot via the assigned GPIO pin

logfile="reboot_internal.log"
reboot_pin=26 # GPIO pin to monitor

# Make sure output is off for a minute (in case it was still on for any reason)
# The internal unit has to see the input low at least once or it will not reboot
# This is to prevent a constant reboot loop if the input goes bad and gets stuck high

printf "%s\t%s\n" "$(date '+%Y%m%d %T')" "Requesting reboot of internal unit via GPIO" >> $logfile

raspi-gpio set $reboot_pin op dl # dl - Drive low
sleep 65

# Set pin high for 6 minutes (internal unit should reboot after 5)
raspi-gpio set $reboot_pin op dh # dh - Drive high
sleep 365

# Turn pin off when complete
raspi-gpio set $reboot_pin op dl # dl - Drive low
