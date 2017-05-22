#!/bin/bash
# Pings addresses in HOSTS list for PINGCOUNT times on network interface IFACE
# If there is a failure to get any ping replies for outagecount tries, perform some action

countfile="reboot_request_count.log"
sanityfile="reboot_request_ok.txt"
logfile="reboot_check.log"
reboot_threshold=5

reboot_pin=26 # GPIO pin to monitor
level="level=1"

total=0

if [ -e $countfile ]
then
    lasttotal=$(cat $countfile)
    #printf "Last Count: %s\n" $lasttotal
else
    lasttotal=0
fi

if sudo raspi-gpio get $reboot_pin | grep -q $level
then
    #printf "Reboot requested\n"
    if [ -e $sanityfile ]
    then
        total=$(($lasttotal + 1))
        printf "%s\t%s\n" "$(date '+%Y/%m%d %T')" "Reboot request $total."  >> $logfile
    else
        printf "%s\t%s\n" "$(date '+%Y/%m%d %T')" "Sanity file not present.  Ignoring reboot request."  >> $logfile
    fi

else
    #printf "Normal\n"
    total=0
    printf "ok" >> $sanityfile
fi

printf "%s" $total > $countfile

if [ $total -ge $reboot_threshold ]
then
    #sudo rm $sanityfile
    printf "%s\t%s\n" "$(date '+%Y/%m%d %T')" "Last $total checks requested reboot. Rebooting..." >> $logfile
    #printf "Last %s checks requested reboot. Rebooting...\n" $total
    printf -1 > $countfile # Set count to -1 when rebooting

    sudo rm $sanityfile && sudo reboot

elif [ $lasttotal -ge 1 ] && [ $total -eq 0 ]; then
    printf "%s\t%s\n" "$(date '+%Y/%m%d %T')" "Reboot request canceled after $lasttotal checks."  >> $logfile
    #printf "Reboot request canceled after $lasttotal checks.\n" 

else
    y=1
fi
