# data-diode
Securely transfer data from a secure network to an untrusted network using Raspberry Pis (effectively a basic unidirectional network device / data diode).

# Secure -> Untrusted transfer between Raspberry Pi units
Each Pi acts as an Ethernet to Serial converter with the 2 Pi units connected via serial port.  Only one of the Tx->Rx pairs is connected so the untrusted side cannot transfer data back to the trusted side.

The serial interface limits throughput, but this design was intended for passing small log/debug files primarily.  Running at a baud rate of 921,600 bps the theoretical max is approximately 110 KB/s.  In testing with the protocol implemented, the Pi could consistently manage approximately 85 KB/s sustained transfer speed (~5 MB/minute).

# Cloud storage / notifications
The upload_data/fileuploader.py script enables uploading files from the untrusted (external network) Pi to a Dropbox folder and sending notifications to a Slack channel when this is done.  

# Remote commands
There is limited support for sending commands to the untrusted Pi via Dropbox (the Pi checks for the presence of a command file).  This enables remotely rebooting or requesting log files.  Using a GPIO pin, a reboot of the secure Pi can also be done.
