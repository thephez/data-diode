#!/bin/sh
# This script reset GPIO pins 16/17 (physical pins 36/11) to default mode

echo "Starting state of GPIO 16/17"
sudo raspi-gpio get 16
sudo raspi-gpio get 17

echo " "
sudo raspi-gpio set 16 ip
sudo raspi-gpio set 17 ip

echo "Ending state of GPIO 16/17 (Should be Inputs)"
sudo raspi-gpio get 16
sudo raspi-gpio get 17
