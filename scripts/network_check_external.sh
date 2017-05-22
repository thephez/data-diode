#!/bin/bash
# Pings addresses in HOSTS list for PINGCOUNT times on network interface IFACE
# If there is a failure to get any ping replies for outagecount tries, perform some action

HOSTS="8.8.8.8 208.67.222.222" # Google Public DNS / OpenDNS
PINGCOUNT=2
IFACE=eth0

countfile="network_down_count.log"
logfile="network_check.log"
outagecount=5

output=0 # GPIO pin to toggle
sleepshort=0.2
sleeplong=0.4
blinkcount=10


function blink_led(){

    x=1
    while [ $x -le $1 ]
        do
            raspi-gpio set $output op dh
            sleep $sleeplong
            raspi-gpio set $output op dl
            sleep $sleepshort

            x=$(( $x + 1 ))

        done

        raspi-gpio set $output op dh
}


total=0

if [ -e $countfile ]
then
    lasttotal=$(cat $countfile)
    printf "Last Count: %s\n" $lasttotal
else
    lasttotal=0
fi

    for Host in $HOSTS
    do
        count=$(ping -c $PINGCOUNT -I $IFACE $Host | grep 'received' | awk -F',' '{ print $2 }' | awk '{ print $1 }')
        if [ $count -eq 0 ]; then
            # 100% failed
            echo "Host : $Host is down (ping failed) at $(date)" >> $logfile
            echo "Down" >> $logfile
            #printf "Host : %s is down (ping failed) at %s\n" $Host $(date) >> $logfile
            total=$(($lasttotal + 1))
        else
            echo "Host : $Host is up (ping ok) at $(date)" >> $logfile
            #printf "Host : %s is up (ping ok) at %s\n" $Host $(date) >> $logfile
            echo "Up" >> $logfile

            total=0
        fi

        #total=$((total + count))
    done

    printf "%s" $total > $countfile

    if [ $total -ge $outagecount ]
    then
        printf "Last %s ping checks failed completely. Rebooting\n" $total >> $logfile
        blink_led $blinkcount
    elif [ $lasttotal -ge $outagecount ] && [ $total -eq 0 ]; then
        printf "Connection restored\n" >> $logfile
        raspi-gpio set $output op dl
    else
        raspi-gpio set $output op dl
        y=1
    fi
