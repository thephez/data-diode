#!/usr/bin/env python
from serial import Serial
import sys
import os
import datetime
import hashlib
import time
import logging
import platform
from logging.handlers import RotatingFileHandler
import shutil
import signal
import atexit
import pwd
import grp

logger = logging.getLogger(__name__)
LOGFILEDIR = '/var/lib/sierra'
LOGFILENAME = os.path.normpath(os.path.join(LOGFILEDIR, 'log-serial-recv.txt'))

INITSTRING = b'' + '<<READY>>'.encode()
FILESTRING = b'' + '<<FILE>>'.encode()
ENDFNAMESTRING = b'' + '<<ENDFNAME>>'.encode()
EOFSTRING = b'' + "<<EOF>>\n".encode()
ENDSTRING = b'' + '<<DONE>>'.encode()
SERVERALIVESTRING = b'' + 'Server Alive\n'.encode()
SERVERALIVE = 0

BAUD = 921600
OUTPUTDIR = '/opt/sierra/file_uploader/uploads/outgoing'
TEMPDIR = '/opt/sierra/serial_receive_tmp'

def configure_logging():
    logger.setLevel(logging.DEBUG)
    logger.setLevel(logging.INFO)
    #logger.setLevel(logging.WARNING)
    formatter = logging.Formatter('%(asctime)s\t%(funcName)s\t%(levelname)s\t%(message)s')

    # Console logging
    ch = logging.StreamHandler()#sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # File logging (Rotating)
    try:
        rfh = RotatingFileHandler(LOGFILENAME, maxBytes=512000, backupCount=5)
        rfh.setFormatter(formatter)
        logger.addHandler(rfh)
    except Exception as e:
        logger.critical('Error accessing log file{}.  Exiting.\n\tException Message: {}'.format(LOGFILENAME, e))
        sys.exit()

def filehash(filepath):
    '''
    Calculate and return the MD5 hash of the file
    '''

    blocksize = 64*1024
    
    md5 = hashlib.md5()
    with open(filepath, 'rb') as fp:
        while True:
            data = fp.read(blocksize)
            if not data:
                break

            md5.update(data)
    return md5.hexdigest()

def recvfile(connection, filename, starttime):
    '''
    Reads incoming data and writes it to the local file
    Provides periodic status update (bytes recvd / transfer rate)
    Detects end of file and invalid data
    Timeout if data transfer stalls
    '''

    chunkcount = 0
    bytestatus = 1000 #Log status every x KB
    totalbytes = 0
    recvdatalen = 0
    nullbytelimit = 100
    nullbytecount = 0
    nullsleeptime = 0.05
    nulltimeout = 15 # Timeout in seconds
    transfererror = False
    lastwriteline = ''
    lastupdate = ''

    connection.rtscts = True
    filename = os.path.normpath(os.path.join(TEMPDIR, filename))
    folderinit(os.path.dirname(filename), 'Receive folder/subfolder')
    logger.info('Writing to: {}'.format(filename))

    with open(filename, "wb") as outfile:
       while True:
            recvdatalen = connection.inWaiting()

            if recvdatalen > 0:
                line = connection.read(recvdatalen)
                totalbytes += len(line)
                chunkcount += 1

                if (int((totalbytes / 1000)) % bytestatus == 0) and (lastupdate != int(totalbytes / 1000)):
                    lastupdate = int(totalbytes / 1000)
                    elapsedtime = (datetime.datetime.now() - starttime).total_seconds()
                    if elapsedtime > 0:
                        transferspeed = (totalbytes / 1024) / (datetime.datetime.now() - starttime).total_seconds()
                    else:
                        transferspeed = 0
                        
                    logger.info('{:,} Bytes Received in {}s ({:d} KB/s) ({:,} Chunks)'.format(totalbytes, round(elapsedtime, 1), int(transferspeed), chunkcount)) #, str(line[0:5]) + '...' + str(line[-5:])))


                if EOFSTRING in line:

                    if line[-8:] == EOFSTRING:
                        outfile.write(line[:-8])
                        totalbytes -= (8 + 0) # Don't count the EOFSTRING - it isn't part of the file
                        logger.debug('\tEOF last 8 characters of line {}'.format(line, lastwriteline))
                        break
                    
                    else:
                        logger.warning('\tEOF somewhere in middle of line {}'.format(line))
                        # This will cause a corrupt file
                        #break
                
                if line != b'':
                    logger.debug('{:,}. ({:,} Bytes) {}'.format(chunkcount, totalbytes, str(line[0:5]) + ' ... ' + str(line[-5:])))
                    outfile.write(line)
                    lastwriteline = line
                    nullbytecount = 0
                
                if INITSTRING in line:
                    raise ValueError('Server sending InitString "{}" in middle of transfer.  Client/Server out of sync!!'.format(INITSTRING))
                
                if FILESTRING in line:
                    raise ValueError('Server sending FileString "{}" in middle of transfer.  Client/Server out of sync!!'.format(FILESTRING))
                
                if ENDSTRING in line:
                    raise ValueError('Server indicating file transmission complete - {} received but no EOF found!!  Last Write: {}'.format(line, lastwriteline))

                time.sleep(0.001) # For some reason, this sleep actually increases transfer rate noticeably 

            else:
                nullbytecount += 1
                if nullbytecount >= (nulltimeout / nullsleeptime): #nullbytelimit:
                    raise Exception('WARNING: No data received for {} seconds. Transmission failed or completed undetected.  Transfer aborted.'.format(nulltimeout))

                time.sleep(nullsleeptime) # This seems to be necessary

    connection.rtscts = False

    return chunkcount, totalbytes

def initRTSDTR(connection):
    logger.debug('Initialize RTS/DTR to Off')
    connection.setDTR(0)
    connection.setRTS(0)
    time.sleep(1)

def isinvalidmsg(message):
    '''
    Checks if the provided message contains any of the reserved keywords
    If it does, the transfer is invalid and an exception will be raised
     to restart the main loop
    '''
    invalidmsg = []
    invalidmsg.append(INITSTRING)
    invalidmsg.append(FILESTRING)
    invalidmsg.append(EOFSTRING)
    invalidmsg.append(ENDSTRING)
    #invalidmsg.append(SERVERALIVESTRING)

    for msg in invalidmsg:
        if msg in message:
            msg = msg.replace('<<', '')
            msg = msg.replace('>>', '')
            raise Exception("Invalid message '{}' found in received data.".format(msg))

    return False

def checkforstring(connection, string, sleeptime):
    '''
    Loops until requested string is found or the timeout is reached
    Logs Server Update messages
    Checks for invalid messages
    '''

    logger.debug('Waiting for String ({})'.format(string))
    
    # Loop until requested string found
    while True:
        incomingdata = connection.readline(connection.inWaiting())
        if incomingdata != string:
            if incomingdata != b'':
                logger.debug('Waiting for String ({}),  Received {}'.format(string, incomingdata))
                if incomingdata == SERVERALIVESTRING:
                    serveralive()
                elif incomingdata[0:13] == 'SERVER UPDATE':
                    logger.info(incomingdata)
                else:
                    pass

                isinvalidmsg(incomingdata) # Check if invalid message received

                time.sleep(0.05) # If data received, sleep shorter to clear out queue
            else:
                time.sleep(sleeptime)
        else:
            logger.info('String ({}) received'.format(string))
            return 1      

def serveralive():
    print('Server Alive message received')
    SERVERALIVE = 1
    return

def checkforfilename(connection):
    '''
    Get the file name sent by the server and return the file name / folder
    Captures ends when ENDFNAMESTRING is received. Reports timeout error if not received
    '''

    filename = ''
    sleeptime = 1
    filenametimeout = 20
    filenametimeoutcount = 0

    while True:
        if connection.inWaiting() < 1:
            logger.debug('Waiting for Remote File Name ({} characters received)'.format(connection.inWaiting()))
            time.sleep(sleeptime)
            filenametimeoutcount += 1
            if filenametimeoutcount > (filenametimeout / sleeptime):
                raise Exception('Timeout waiting for filename.  Filename not received within {} seconds.'.format(filenametimeout / sleeptime))
        else:
            filenametimeoutcount = 0
            filename = filename + connection.read(connection.inWaiting())
            filename = filename.decode().rstrip('\0')
            isinvalidmsg(filename) # Checks for reserved string (INITSTRING, etc.)
                
            logger.debug('Filename data received: {}'.format(filename))

            if ENDFNAMESTRING in filename:
                logger.info('ENDFNAME string ({}) found'.format(ENDFNAMESTRING))
                filename = filename[:-12]
                filename += '.part'
                subfolder = os.path.dirname(filename)

                return filename, subfolder

            time.sleep(1)

    return -1

def getremotehash(connection):
    '''
    Read the file hash sent by the server
    Captures [hashlength] characters and reports timeout error if not received
    '''

    remotehash = ''
    sleeptime = 1
    hashtimeout = 10
    hashtimeoutcount = 0
    hashlength = 32

    while True:
        if connection.inWaiting() < hashlength:
            logger.debug('Waiting for Remote File Hash ({} characters received)'.format(connection.inWaiting()))
            time.sleep(sleeptime) # 1
            hashtimeoutcount += 1
            if hashtimeoutcount > (hashtimeout / sleeptime):
                raise Exception('Timeout waiting for remote hash.  Hash not received within {} seconds.'.format(hashtimeout / sleeptime))
        else:
            break

    if connection.inWaiting() > hashlength:
        logger.warning("Buffer contains {} characters. Expected hash length is only {} characters.".format(connection.inWaiting(), hashlength))

    remotehash = connection.readline(hashlength) # connection.inWaiting())
    remotehash = remotehash.decode().rstrip('\0')

    return remotehash

def getportname():
    '''
    Use /dev port if on Raspberry Pi (arm processor)
    '''

    if platform.system() == 'Linux':
        if os.uname()[4][:3] == 'arm':
            logger.info('Linux detected (ARM processor).  Raspberry Pi environment likely.  Defaulting to /dev/ttyAMA0')
            return '/dev/ttyAMA0'
        else:
            logger.info('Generic Linux detected.  Defaulting to first COM Port')
            return 0
    elif platform.system() == 'Windows':
        logger.info('Windows detected. Defaulting to first COM Port')
        return 'COM1'
    else:
        return 0 # Interpreted by Pyserial as the first serial port

def tempfilecleanup(transferstatus, filename, subfolder):
    '''
    Move temp file to output folder for upload
    Use separate service to manage the uploads
    '''

    tempfile = filename
    corruptfile = os.path.normpath(os.path.join(TEMPDIR, subfolder, os.path.basename(filename +'.000')))
    outputfile = os.path.normpath(os.path.join(OUTPUTDIR, subfolder, os.path.basename(filename)))[:-5]
    folderinit(os.path.join(OUTPUTDIR, subfolder), 'Output Folder/Subfolder')

    try:
        if transferstatus:
            logger.info('Moving temp file "{}" to output folder "{}"'.format(tempfile, os.path.join(OUTPUTDIR, subfolder)))
            shutil.move(tempfile, outputfile)
            chown(outputfile)
        else:
            # Eventually delete corrupt files, currently renaming for debugging use
            logger.info('Corrupt temp file "{}"'.format(tempfile))
            #os.remove(tempfile)
            os.rename(tempfile, corruptfile)
            chown(corruptfile)

    except Exception as e:
        logger.critical('Exception cleaning up temp file {}.\n\tException Message: {}'.format(tempfile, e))

    return

def logtouploader(filename):
    '''
    Moves the file to the Log Output folder
    '''
    
    outputfile = os.path.normpath(os.path.join(OUTPUTDIR, 'logs', os.path.basename(filename)))
    folderinit(os.path.normpath(os.path.join(OUTPUTDIR, 'logs')), 'Log Output folder')

    try:
        shutil.copy2(filename, outputfile)
        chown(filename)
    except Exception as e:
        logger.warning('Log file "{}" could not be copied to upload folder.\n\tException Message: {}'.format(filename, e))
    
    return

def getpid():
    '''
    Used to help prevent more than one instance of the program from running
    The PID file is also monitored by a cron that will restart the program if a
     process using the PID in the file is not found

    Get the process ID (PID) from the OS
    If the PID file already exists, read the PID in the file, kill that process,
     and delete the current file
    Write the new PID to the file
    '''

    pid = str(os.getpid())
    pidfile = '/tmp/serial-recv-file.pid'

    if os.path.isfile(pidfile):
        logger.warning('{} already exists'.format(pidfile))
        with open(pidfile, 'r') as existingfile:
            existingpid = existingfile.readline()

        logger.warning('Process running as PID {} (or process did not exit cleanly).  Ending existing process.'.format(existingpid))
        try:
            os.kill(int(existingpid), signal.SIGKILL) #SIGTERM
        except Exception as e:
            logger.warning('Exception when killing PID {}.\n\tException Message: {}'.format(existingpid, e))

        os.unlink(pidfile)

    with open(pidfile, 'w') as file:
        file.write(pid)

    logger.info('PID File {} written. Process running as PID {}.'.format(pidfile, pid))
    return pid, pidfile

def folderinit(dirname, diruse):
    
    try:
        if not os.path.exists(dirname):
            logger.warning('{} ({}) does not exist. Attempting to create.'.format(diruse, dirname))
            os.makedirs(dirname)
            chown(dirname)

    except Exception as e:
        logger.critical('Exception creating {} ({})\n\tException Message: {}'.format(diruse, dirname, e))

    return

def chown(path, user="controls", group="sierra"):
    '''
    Change the owner/group of the provided filesystem path
    '''

    uid = pwd.getpwnam(user).pw_uid
    gid = grp.getgrnam(group).gr_gid
            
    os.chown(path, uid, gid)


def removepid(pidfile, pid):
    print('Exiting and removing PID file {} (PID #{})'.format(pidfile, pid))
    logger.info('Exiting and removing PID file {} (PID #{})'.format(pidfile, pid))   

    try:
        os.unlink(pidfile)
    except Exception as e:
        logger.critical('Exception deleting {} ({}\n\tException Message: {}'.format(diruse, dirname, e))
   
    return

def openserialport():
    '''
    Attempt to open a serial connection using the baud rate defined in the BAUD global variable
     and continue retrying until successful.
    On successful connection, send a message out the port, return the connection to the calling function,
     and register with atexit to close the serial port when the program exits
    '''

    while True:
        try:
            ser = Serial(port=getportname(), baudrate=BAUD, bytesize=8, parity='N', stopbits=1, timeout=None, xonxoff=0, rtscts=0)
            atexit.register(closeserialport, connection=ser)
            logger.info('-'*30 + ' Serial Port opened ' + '-'*30)
            logger.info('Serial port opened successfully.\n\tPort Configuration: {}'.format(ser))
            return ser
        except Exception as e:
            logger.critical('Exception opening serial port. Retrying...\n\tException Message: {}'.format(e))

        time.sleep(10)

    return ser            

def closeserialport(connection):
    initRTSDTR(connection)
    print('Closing Comm. Port {}.'.format(connection))
    connection.close()
    logger.info('-'*30 + ' Serial Port closed ' + '-'*30)

    return


def main():
    filename = ''
    chunkcount = 0
    totalbytes = 0

    folderinit(LOGFILEDIR, 'LOGFILEDIR')
    configure_logging()

    if os.getuid() != 0:
        print('Cannot run as a normal user. Root access required to open the serial port - try calling via sudo.')
        logger.critical('Cannot run as a normal user. Root access required to open the serial port - try calling via sudo.')
        sys.exit()

    pid, pidfile  = getpid()
    atexit.register(removepid, pidfile=pidfile, pid=pid)

    folderinit(TEMPDIR, 'TEMPDIR')

    ser = openserialport()

    while True:

        if ser.isOpen() == False:
            try:
                logger.warning('Serial port no longer open. Attempting to re-open.')
                ser.open()
                logger.warning('Serial port re-opened successfully.\n\tPort Configuration: {}'.format(ser))
            except Exception as e:
                logger.critical('Exception opening serial port. Retrying...\n\tException Message: {}'.format(e))
           
        try:
            filename = ''
            subfolder = ''
            chunkcount = 0
            totalbytes = 0

            initRTSDTR(ser)
            logger.info('-'*30 + ' Waiting for file ' + '-'*30)

            result = checkforstring(ser, INITSTRING, 5)
            ser.setRTS(1)

            result = checkforstring(ser, FILESTRING, 1)    
            ser.setRTS(0)

            filename, subfolder = checkforfilename(ser)

            starttime = datetime.datetime.now()
            ser.setRTS(1) # Tell server to start sending
            logger.info('Received InitString ({}), FileString ({}), and Filename received\n\tFile ({}) requested @ {}'.format(INITSTRING, FILESTRING, filename, str(starttime)))

            chunkcount, totalbytes = recvfile(ser, filename, starttime)
            logger.info('File received: {:,} Bytes (in {:,} Chunks)'.format(totalbytes, chunkcount))

            endtime = datetime.datetime.now()

            ser.setRTS(1) # Tell server to resume sending
            result = checkforstring(ser, ENDSTRING, 1)
            logger.debug('Server indicated transmission complete via EndString ({}) @ ({})\n'.format(ENDSTRING, datetime.datetime.now()))
            ser.setRTS(1) # Tell server to resume sending

            remotehash = getremotehash(ser)

            ser.setRTS(0) # Turn off RTS
            ser.setDTR(1) # Turn on to indicate hash check started

            filename = os.path.normpath(os.path.join(TEMPDIR, filename))    
            hashvalue = filehash(filename)

            if hashvalue != remotehash:
                logger.warning('Transfer Failure - Hash Mismatch!!\n\tLocal File Hash \t= {}\n\tRemote File Hash\t= {}'.format(hashvalue, remotehash))
                ser.setRTS(0) # Turn off to indicate failure
                ser.setDTR(0) # Turn off to indicate hash check done
                tempfilecleanup(False, filename, subfolder)
            else:
                logger.info('Transfer Success - Hashes Match (File Hash = {})'.format(hashvalue))
                ser.setRTS(1) # Turn on to indicate success
                ser.setDTR(0) # Turn off to indicate hash check done
                tempfilecleanup(True, filename, subfolder)

            transferspeed = (totalbytes / 1024) / (endtime - starttime).total_seconds()
            logger.info('Transfer finished @ {}\tElapsed Time: {} ({} KB/s)'.format(str(endtime), str(endtime - starttime), round(transferspeed, 1)))
            logger.info('-'*30 + ' End of transfer ' + '-'*30)
            logtouploader(LOGFILENAME)
            time.sleep(5)

        except KeyboardInterrupt as e:
            logger.warning('Keyboard Interrupt. Exiting program...\n\tException Message: {}'.format(e))        
            break

        except Exception as e:
            logger.critical('Exception in main loop. Restarting...\n\tException Message: {}'.format(e))        

if __name__ == '__main__':
    main()
