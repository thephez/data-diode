#!/bin/sh
# Configure the following parameters - most importantly 'server'.
# Timeout, User, and Mountpoint should not need to change.

server="<SERVERNAME>"
connecttimeout=10 # Time before SSH connection times out and fails (seconds)

user="controls"
mountpoint="/tmp/server"
logdir="/var/lib/sierra"

# Make sure mountpoint is present
mkdir -p $mountpoint

printf "%s\t%s\n" "$(date '+%Y/%m/%d %T')" "-------------------- Checking SSHFS Mount --------------------" >> $logdir/log-sshfs-mount.log

if sudo df -h | grep -q $server
then
   echo "Already mounted. Skipping."
   printf "$(date '+%Y/%m/%d %T')\tAlready mounted.\n" >> $logdir/log-sshfs-mount.log

else
   echo "Not mounted"
   printf "$(date '+%Y/%m/%d %T')\tNot mounted. Attempting SSHFS connection.\n" >> $logdir/log-sshfs-mount.log
   sudo sshfs $user@$server:/server/ $mountpoint -o reconnect -o workaround=all -o ssh_command=ssh -o ConnectTimeout=$connecttimeout

   printf "$(date '+%Y/%m/%d %T')\tSSHFS mount attempt done. Checking for mount point via disk usage.\n" >> $logdir/log-sshfs-mount.log
   printf "%s\t%s\n" "$(date '+%Y/%m/%d %T')" "Disk Usage output: $(sudo df -h | grep /tmp/server)" >> $logdir/log-sshfs-mount.log

   # Check if mounted successfully
   if sudo df -h | grep -q $server
   then
      echo "Mounted successfully as '$mountpoint'"
      printf "$(date '+%Y/%m/%d %T')\tMounted successfully as '$mountpoint'.\n" >> $logdir/log-sshfs-mount.log

   else
      echo "Mount failed!"
      printf  "$(date '+%Y/%m/%d %T')\tMount failed!\n" >> $logdir/log-sshfs-mount.log

   fi

fi


