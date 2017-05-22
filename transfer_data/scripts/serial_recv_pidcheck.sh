#!/bin/bash

function start_service(){
	# Start process back up
	echo "Restarting process"
	date >> $LOG
        echo "Restarting closed process" >> $LOG
	cd /opt/sierra/data_diode/transfer_data/
	./serial-recv-file.py &
}

function check_for_root(){
	if [ "$(whoami)" != "root" ];then
		echo "Error: Must be run as root"
		exit 1
	fi
}

# Use this to read in the last value returned (so we get an accurate one below)
flushreturn=$?

FILE=/tmp/serial-recv-file.pid
LOG=/var/lib/sierra/serial-recv-pidcheck.txt
echo "Checking if file $FILE exists."

if [ ! -f $FILE ];then
	echo "File $FILE does not exist! Service will be started."
	check_for_root
	start_service
else
	while read line || [ -n "$line" ];do pid=$line #echo "Line: $line"
	pid=$line
	done < $FILE

	echo "PID = $pid - Checking if process still running..."

	# Check if PID running by issuing kill -0 and reading the return value
	check_for_root
	kill -0 $pid
	result=$?

	if [ $result -eq 0 ];then
		echo "PID $pid is running"
	else
		echo "PID $pid is not running!"
		start_service
	fi
fi
