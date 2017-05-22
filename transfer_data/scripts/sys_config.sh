#!/bin/sh

#############################################################################################################
#
# This script does the following:
# - Verify serial port settings and adjust if necessary (disable login shell on ttyAMA0, set baud to 921600)
# - Check keyboard settings and prompt to update if not English (US) (opens raspi-config)
# - Remove unecessary packages
# - Install required software
# - Create group / user. Sets permissions. Installs SSH key
# - Clone repository / create folders with correct permmissions
# - Upgrade OS files
# - Remove unecessary files left over after software installs / uninstalls
# - Install shortcuts for configuring with send, receive, or upload functions
# - Install shortcut for automated network security setup (firewall config, SSH restrictions)
# - Install shortcut for Server Shared folder (SSHFS) connection configuration
#
#############################################################################################################

repo="http://192.168.1.111:8000/"
repofolder="data_diode"
required_locale="en_US"

function check_serial_port(){
   # Function to check the /boot/cmdline.txt file to see if a login shell is enabled
   #  on ttyAMA0.  It must be disabled for the Data Diode to work properly since it
   #  uses that serial port

   echo "Checking serial port boot configuration"
   log_msg "Checking serial port boot configuration"

   searchstring="ttyAMA0"
   file="/boot/cmdline.txt"

   if grep -q $searchstring $file
   then
      echo " "
      echo "-------------------------------------------------------------------------------------------"
      echo "                        WARNING!"
      echo " '$searchstring' found in $file.  Login shell on $searchstring not disabled!"
      grep $searchstring $file
      echo " "
      #echo " Run 'sudo raspi-config' and modify:"
      #echo "   9. Advanced Options -> A8. Serial (disable login shell on serial port)"
      #echo " "
      #read -p "Press [Enter] to open raspi-config..."
      #sudo raspi-config

      read -p "Press [Enter] to update $file to disable the login shell on $searchstring."
      # Automatically remove the console=ttyAMA0,115200 entry (copied from /usr/bin/raspi-config script)
      sudo sed -i /boot/cmdline.txt -e "s/console=ttyAMA0,[0-9]\+ //"
      echo " "
      echo " Updated $file:"
      cat $file
      echo " "

      # Following line re-enables login shell on ttyAMA0 (copied from /usr/bin/raspi-config script)
      #sudo sed -i /boot/cmdline.txt -e "s/root=/console=ttyAMA0,115200 root=/"

   else
      echo " Serial Port configured properly ('$searchstring' not found in $file)"
   fi

   #read -p "Exiting Serial Port Configuration. Press [Enter] to proceed..."
   echo " "
}

function check_locale(){
   echo "Checking Locale for US configuration"
   searchstring=$required_locale

   if locale | grep -q $searchstring
   then
      echo " Locale configured properly. ('$searchstring' found in locale)"
   else
      echo " '$searchstring' found in locale."
      echo " Locale must be modified so the English (US) keyboard can be used."
      echo " Run 'sudo raspi-config' and modify:"
      echo "   5. Internationalisation Options -> 1. Change Locale. Set to 'en_US.UTF-8 UTF-8'"
      echo "   5. Internationalisation Options -> 3. Change Keyboard Layout. Set to 'English (US)'"
      read -p "Press [Enter] to open raspi-config..."
      sudo raspi-config

      read -p "Reboot required to apply keyboard changes. Press [Enter] to reboot or [Ctrl-C] to exit..."
      sudo reboot
   fi

   #read -p "Exiting Locale Check. Press [Enter] to proceed..."
}

function check_keyboard(){
   echo "Checking Keyboard for US configuration"
   log_msg "Checking Keyboard for US configuration"

   if grep -q 'XKBLAYOUT="us"' /etc/default/keyboard
   then
      echo " Keyboard configured properly (English (US))"
   else
      echo " Keyboard not configured as English (US)."
      echo " Keyboard must be modified so the English (US) keyboard can be used."
      echo " Run 'sudo raspi-config' and modify:"
      echo "   5. Internationalisation Options -> 3. Change Keyboard Layout. Set to 'English (US)'"
      read -p "Press [Enter] to open raspi-config..."
      sudo raspi-config

      read -p "Reboot required to apply keyboard changes. Press [Enter] to reboot or [Ctrl-C] to exit..."
      sudo reboot
   fi

   #read -p "Exiting Keyboard Check. Press [Enter] to proceed..."
}

function log_msg(){
   echo -e $(date '+%Y/%m/%d %T')"\t"$1 >> sys_config_log.log
}


clear

# Check Pre-reqs
log_msg "--------------- System Configuration Script Starting ---------------"
log_msg "Checking Configuration Prerequisites"
echo "Checking Configuration Prerequisites"
check_serial_port
check_keyboard
#check_locale
echo " "

# Update software repo
   echo " "
   log_msg "Updating Software Package List ('sudo apt-get update')"
   echo "Update Software Package List."
   sudo apt-get update
   echo " "

# Remove unused packages
   log_msg "Removing unused packages"

   echo "Remove Wolfram"
   echo "##############"
   sudo apt-get -y purge wolfram-engine
   echo " "

   echo "Remove LibreOffice"
   echo "##################"
   sudo apt-get -y purge libreoffice*
   echo " "

   echo "Remove Misc. packages"
   echo "#####################"
   sudo apt-get remove --purge minecraft-pi python3-minecraftpi sonic-pi nuscratch scratch
   sudo apt-get remove --purge  smartsim penguinspuzzle python-minecraftpi 
   sudo apt-get remove --purge oracle-java8-jdk
   echo " "

echo "Disk usage"
   df -h

echo " "
   log_msg "Installing Comm. / GPIO software"
   echo "Installing Comm. / GPIO software"
   echo "################################"
   sudo apt-get -y install minicom python-rpi.gpio raspi-gpio
   sudo apt-get -y install slurm tcpdump
   echo " "

echo "Installing version control software"
echo "###################################"
   log_msg "Installing version control software"
   sudo apt-get -y install mercurial #tortoisehg # tortoisehg not required (no GUI installed)
   # Write basic .hgrc file if it doesn't exist
   if [ ! -f ~/.hgrc ]; then
      echo "Writing user .hgrc file (~/.hgrc) "
      echo [ui] >> ~/.hgrc
      echo username = Raspberry Pi >> ~/.hgrc
   fi
   echo " "

echo "Installing VPN, SSHFS, UFW (Firewall)"
echo "##########################"
   log_msg "Installing VPN, SSHFS, UFW (Firewall)"
   sudo apt-get -y install vpnc sshfs ufw #tightvncserver #this forces an install of all the X (GUI) stuff
   sudo apt-get -y install --reinstall iputils-ping #resolve issue that requires root for pinging
   echo " "

# Python modules
   echo "Installing Python modules"
   echo "#########################"
   log_msg "Installing Python modules"

   # pip may break after installing an updated 'requests' package if it 
   #  is not update.  easy_install may be required to do this
   log_msg "Updating pip"
   sudo apt-get -y install python-pip
   sudo pip install --upgrade pip || sudo easy_install --upgrade pip

   log_msg "Installing GPIO Zero"
   sudo apt-get -y install python-gpiozero python3-gpiozero

   # Required for Data Diode
   log_msg "Installing PySerial, Dropbox, Slack, Config Parser"
   sudo pip install pyserial dropbox slacker configparser
   echo " "

   # Eliminate Dropbox security warnings
   sudo apt-get -y install build-essential libssl-dev python-dev libffi-dev
   sudo pip install --upgrade ndg-httpsclient
   sudo pip install 'request[security]'
   echo " "

echo "----------------------------------------"
echo " -------- User and Group Config ------- "
echo "########################################"
log_msg "User and Group Config"
   sudo addgroup sierra

   echo " -------- Adding user 'controls' ------ "
   sudo adduser controls
   sudo usermod -aG sierra controls
   sudo usermod -aG audio controls
   sudo usermod -aG video controls
   sudo usermod -aG gpio controls # Allows non-root access to GPIO
   echo " "

   # Folder permissions / groups
   sudo mkdir -p /var/lib/sierra
   sudo chgrp sierra /var/lib/sierra
   sudo chmod 775 /var/lib/sierra

   sudo mkdir -p /opt/sierra
   sudo chgrp sierra /opt/sierra
   sudo chmod 775 /opt/sierra
   sudo mkdir -p /opt/sierra/file_uploader/uploads/outgoing/logs
   sudo chgrp sierra -R /opt/sierra/file_uploader
   sudo chmod 775 -R /opt/sierra/file_uploader/

   echo "Make sure controls user has sudo access."
   if sudo cat /etc/sudoers | grep controls
   then
      log_msg "Controls user already has sudo access."
      echo "Controls user has sudo access."
   else
      log_msg "Asking user to assign sudo access for controls user account"
      echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
      echo " Give 'controls' user sudo access"
      echo " Make sure the following line is at the end of the document:"
      echo " "
      echo "    controls ALL=(ALL) PASSWD: ALL"
      echo " "
      echo " File will now be opened via 'sudo visudot'"
      echo " To close the file after editing, press Ctrl-x, y, Enter"
      echo " "
      read -p "Press [Enter] to proceed open the file..."
      sudo visudo
   fi


# Write setup script to controls home directory if it doesn't exist
#if [ ! -f ~/setup.sh ]; then
   echo "#!/bin/sh" > ~/setup.sh
   echo "ls /opt/sierra/" >> ~/setup.sh
   echo "cd /opt/sierra/" >> ~/setup.sh

   echo "echo Cloning Repository" >> ~/setup.sh
   echo "hg clone $repo $repofolder" >> ~/setup.sh

   echo "echo ##################################################" >> ~/setup.sh
   echo "cd" >> ~/setup.sh
   echo "mkdir -p ~/.ssh" >> ~/setup.sh
   echo "echo Importing controls SSH public key" >> ~/setup.sh

   echo "echo <Generate a SSH key pair and insert public key here> > ~/.ssh/authorized_keys" >> ~/setup.sh

   echo "chmod 700 ~/.ssh" >> ~/setup.sh
   echo "chmod 600 ~/.ssh/authorized_keys" >> ~/setup.sh
   echo "echo ##################################################" >> ~/setup.sh
   echo "ln -s /opt/sierra/data_diode/transfer_data/scripts/create_serial_send_startup_cron ~/Sending_Secure_Network_Setup_script" >> ~/setup.sh
   echo "ln -s /opt/sierra/data_diode/transfer_data/scripts/create_serial_recv_startup_cron ~/Receiving_External_Network_Setup_script" >> ~/setup.sh
   echo "ln -s /opt/sierra/data_diode/upload_data/scripts/create_fileuploader_cron ~/Uploader_External_Network_Setup_script" >> ~/setup.sh
   echo "ln -s /opt/sierra/data_diode/transfer_data/scripts/network_security_setup_script.sh ~/Network_Security_Setup_script" >> ~/setup.sh
   echo "ln -s /opt/sierra/data_diode/transfer_data/scripts/sshfs_connection_setup_script ~/Server_Share_SSHFS_Connection_Setup_script" >> ~/setup.sh
   echo "ln -s /opt/sierra/data_diode/transfer_data/scripts/logrotate_setup_script ~/Log_Rotate_Setup_script" >> ~/setup.sh
   #echo "ls -al" >> ~/setup.sh


   echo "echo ##################################################" >> ~/setup.sh
   echo "echo Logging out of controls account" >> ~/setup.sh
   echo "exit" >> ~/setup.sh
#fi


# Check/configure installed software

   # GPIO Check
   echo "Running 'raspi-gpio get' (should return status of GPIO) "
   echo "#######################################################"

   raspi-gpio get
   log_msg "Asking user to verify GPIO status"
   echo "GPIO status should be shown above (via 'raspi-gpio get' command)"
   read -p "Press [Enter] to continue..."

   # VNC Config
   mkdir -p ~/.vnc
   chmod go-rwx ~/.vnc
   log_msg "Asking user to assign VNC password"
   printf "\nSet VNC password\n"
   printf "####################"
   vncpasswd
   # Set password (doesn't work)
   #sudo vncpasswd -f <<<password >~/.vnc/passwd

   # Create Cisco VPN connection conf file (minus passwords)
   if [ ! -f ~/SDS_VPN.conf ]; then
      echo "#IPSec gateway <Replace with VPN domain name (i.e. vpn.domain.com)> # Remove '#' at star of line to uncomment" > ~/SDS_VPN.conf
      echo "#IPSec ID <Replace with Cisco VPN ID (i.e. WORK_VPN)> # Remove '#' at star of line to uncomment" >> ~/SDS_VPN.conf
      echo "#IPSec secret <Replace with Group Password> # Remove '#' at star of line to uncomment" >> ~/SDS_VPN.conf
      echo "#Xauth username <Replace with username> # Remove '#' at star of line to uncomment" >> ~/SDS_VPN.conf
      echo "#Xauth password <Replace with password> # Remove '#' at star of line to uncomment" >> ~/SDS_VPN.conf
   fi


   if sudo cat /boot/config.txt | grep -q "init_uart_clock=14745600"
   then
      printf "\nMax baud rate of 921,600 already enabled in /boot/config.txt.  Not changing.\n"
      log_msg "Baud rate of 921,600 already enabled."
   else
      clear
      log_msg "Updating /boot/config.txt to enable 921,600 baud"
      echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
      echo " Adding the init_uart_clock line to the end of /boot/config.txt"
      echo " Make sure there is only one entry like this in the file"
      echo " "
      echo "    init_uart_clock=14745600"
      echo " "
      echo " File will now be opened via 'sudo nano /boot/config.txt'"
      echo " To close the file after editing, press Ctrl-x, y, Enter"
      echo " "
      read -p "Press [Enter] to proceed open the file..."

      sudo sh -c 'echo " " >> /boot/config.txt'
      sudo sh -c 'echo "# Adjust UART clock to enable 921,600 baud (14745600 / 16) " >> /boot/config.txt'
      sudo sh -c 'echo "init_uart_clock=14745600" >> /boot/config.txt'
      log_msg "Asking user to verify UART clock change in /boot/config.txt"
      sudo nano /boot/config.txt
   fi

echo " "
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo " Login as 'controls' and run: '. /home/controls/setup.sh' to finish setup "

sudo cp ~/setup.sh /home/controls
sudo chown controls /home/controls/setup.sh
sudo chmod 755 /home/controls/setup.sh
sudo chgrp controls /home/controls/setup.sh

sudo cp ~/.hgrc /home/controls
sudo chown controls /home/controls/.hgrc
sudo chgrp controls /home/controls/.hgrc

# Request controls login and run setup.sh
log_msg "Asking user to login as controls in order to run setup.sh script"
su -c '. ~/setup.sh' controls

# Install logrotate config
echo " "
echo "Installing logrotate configuration"
echo "##################################"
log_msg "Installing logrotate configuration"
. /opt/sierra/data_diode/transfer_data/scripts/logrotate_setup_script


# Upgrade OS / software
printf "\n\n\n"
echo "Update/Upgrade Operating System and software now?  This may take a long time on the initial install (1 hr+)"
echo "Recommend for intial install.  Optional once system configured."
printf "\n"
read -p "Update/Upgrade now? [y/n]" -n 1 -r
if [[ $REPLY =~ ^[Yy]$ ]]
then
   echo " "
   echo "Upgrade Starting"
   echo "################"

   log_msg "Upgrade Starting"
   sudo apt-get -y upgrade # Only run this on initial install
   echo " "
   echo "Upgrade complete"
   echo "################"
   log_msg "Upgrade complete"
   df -h
else
   log_msg "Update/Upgrade declined."
fi

# Clean up files (save space)
   printf "\n\nCleaning up package files\n"
   printf "#########################\n"
   log_msg "Cleaing up package files"
   sudo apt-get -y autoremove
   sudo apt-get clean
   printf "Extraneous files removed\n"
   df -h

printf "\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo " System should now be rebooted "
echo " Run 'sudo reboot' and log in as controls after rebooting"
read -p "Reboot required. Press [Enter] to reboot now or [Ctrl-C] to exit..."
read -p "Are you sure you want to reboot now? [y/n]" -n 1 -r
if [[ $REPLY =~ ^[Yy]$ ]]
then
   log_msg "Rebooting..."
   log_msg "--------------- System Configuration Script Exiting (Reboot) ----------------"
   sudo reboot
fi

log_msg "--------------- System Configuration Script Exiting (No Reboot) ----------------"
