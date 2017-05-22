#!/bin/sh
# This script sets up CTS/RTS for UART0 by setting GPIO pins 16/17 
#  (physical pins 36/11) to Alt3 mode

echo "Starting state of GPIO 16/17"
sudo raspi-gpio get 16
sudo raspi-gpio get 17

echo " "
sudo raspi-gpio set 16 a3
sudo raspi-gpio set 17 a3

echo "Ending state of GPIO 16/17 (Should be CTS/RTS)"
sudo raspi-gpio get 16
sudo raspi-gpio get 17
