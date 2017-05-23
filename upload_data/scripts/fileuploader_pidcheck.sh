#!/bin/bash

function start_service(){
	# Start process back up
	echo "Restarting process"
	date >> $LOG
        echo "Restarting closed process" >> $LOG
	cd ~
	cd /opt/sierra/data_diode/upload_data
	./fileuploader.py &
}

function check_for_root(){
	if [ "$(whoami)" != "root" ];then
		echo "Error: Must be run as root"
		exit 1
	fi
}

# Use this to read in the last value returned (so we get an accurate one below)
flushreturn=$?

FILE=/tmp/fileuploader.pid
LOG=/var/lib/sierra/file-uploader-pidcheck.txt
echo "Checking if file $FILE exists."

if [ ! -f $FILE ];then
	echo "File $FILE does not exist! Service will be started."
	start_service
else
	while read line || [ -n "$line" ];do pid=$line #echo "Line: $line"
	pid=$line
	done < $FILE

	echo "PID = $pid - Checking if process still running..."

	# Check if PID running by issuing kill -0 and reading the return value
	#check_for_root
	kill -0 $pid
	result=$?

	if [ $result -eq 0 ];then
		echo "PID $pid is running"
	else
		echo "PID $pid is not running!"
		start_service
	fi
fi
