#!/bin/sh
# This script will configure the firewall to only allow incoming connections via SSH
#   and block root logins via SSH
#
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!IMPORTANT NOTE !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# THE SSH PORT IS CHANGED TO PORT 22223 SO IT WILL BE NECESSARY TO MANUALLY ENTER
#   THIS PORT WHEN CONNECTING (VIA PUTTY, ETC.)
#
# The script also (optionally) will enable/disable ping responses


logfile=network_security_setup.log

function print_msg(){
   echo " "
   echo $1
}

function log_msg(){
#   date >> $logfile
   # Send parameter received (message) to logfile
   echo -e $(date '+%Y/%m/%d %T')"\t"$1 >> $logfile
}

function ufw_ping_config(){
   read -p "Do you want to enable ping responses? [y/n] " -n 1 -r

   file=/etc/ufw/before.rules
   # Backup existing file
   sudo cp $file ~/before.rules.bak

   if [[ $REPLY =~ ^[Yy]$ ]]
   then
      # Enable ping response
      sudo sed -i /etc/ufw/before.rules -e "s/#-A ufw-before-input -p icmp --icmp-type echo-request -j ACCEPT$/-A ufw-before-input -p icmp --icmp-type echo-request -j ACCEPT/"
      print_msg "Ping responses enabled"
      log_msg "Ping responses enabled"
   else
      # Disable ping response
      sudo sed -i /etc/ufw/before.rules -e "s/-A ufw-before-input -p icmp --icmp-type echo-request -j ACCEPT$/#-A ufw-before-input -p icmp --icmp-type echo-request -j ACCEPT/"
      print_msg "--- Ping responses disabled!!! ---"
      log_msg "Ping responses disabled"
   fi
}

function sshd_setup(){

   file=/etc/ssh/sshd_config
   # Backup existing file
   sudo cp $file ~/sshd_config.bak

   # Display current file entries
   echo "Before updates"
   sudo cat $file | grep Port
   sudo cat $file | grep PermitRootLogin
   sudo cat $file | grep "PasswordAuthentication "

   # Change SSH to port 22223 and disable root login
   log_msg "Changing SSH Port to 22223, disabling root login, and disabling password login"
   print_msg "Changing SSH Port to 22223, disabling root login, and disabling password login"
   sudo sed -i $file -e "s/^Port 22$/Port 22223/"
   sudo sed -i $file -e "s/^PermitRootLogin without-password/PermitRootLogin no/"
   sudo sed -i $file -e "s/^#PasswordAuthentication yes/PasswordAuthentication no/"

   # Display current file entries
   echo "After updates"
   sudo cat $file | grep Port
   sudo cat $file | grep PermitRootLogin
   sudo cat $file | grep "PasswordAuthentication "
   echo " "
}

# Configure SSH (change port / disable root login)
sshd_setup

# Enable/Disable ping responses
ufw_ping_config

# Enable and configure firewall for SSH access only
print_msg "Current firewall status ('sudo ufw status')"
sudo ufw status

print_msg "Adding firewall rules"
# SSH
sudo ufw allow ssh
sudo ufw allow 22223 # Alternative SSH Port

print_msg "Starting firewall "
sudo ufw enable

print_msg "Current firewall status ('sudo ufw status')"
sudo ufw status

print_msg "Restarting firewall service to apply changes."
print_msg "NOTE: Ping enable/disable may require a reboot! -----------"
print_msg "NOTE: AFTER REBOOTING ALL SSH CONNECTIONS MUST NOW USE PORT 22223 (instead of the default 22)"
print_msg "NOTE: AFTER REBOOTING ALL SSH CONNECTIONS MUST NOW USE PORT 22223 (instead of the default 22)"
print_msg "NOTE: AFTER REBOOTING ALL SSH CONNECTIONS MUST NOW USE PORT 22223 (instead of the default 22)"

sudo service ufw restart
