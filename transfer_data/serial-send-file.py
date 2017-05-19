#!/usr/bin/env python
from __future__ import division
from serial import Serial
import time
import datetime
import hashlib
import sys
import os
import logging
from logging.handlers import RotatingFileHandler
import platform
import shutil
import signal
import atexit

logger = logging.getLogger(__name__)
LOGFILEDIR = '/var/lib/sierra'
LOGFILENAME = os.path.normpath(os.path.join(LOGFILEDIR, 'log-serial-send.txt'))

INITSTRING = '<<READY>>'.encode()
FILESTRING = '<<FILE>>'.encode()
ENDFNAMESTRING = '<<ENDFNAME>>'.encode()
ENDSTRING = '<<DONE>>'.encode()
SERVERALIVESTRING = 'Server Alive\n'.encode()

ROOT = '/tmp/server/uploads/'
SRCDIR = os.path.normpath(os.path.normpath(os.path.join(ROOT, 'incoming/')))
FAILDIR = os.path.normpath(os.path.join(ROOT, 'failed/'))
DONEDIR = os.path.normpath(os.path.join(ROOT, 'transferred/'))
CACHEDIR = '/opt/sierra/serial_send_files/'
IGNOREDFILES = ['Thumbs.db']

BAUD = 921600

class InvalidMsgError(Exception):
    pass

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

def sendfiledata(connection, filename, filesize):
    '''
    Sends the file via the serial connection and
     uses RTS/CTS for flow control (timeout if CTS not received)
    Checks for invalid strings in the message
    '''

    # Chunksize has a significant impact on CPU usage
    # On the Raspberry Pi at 921,000 baud, 1536 is the sweet spot
    # of CPU usage (~25-40%) and transfer rate
    # Going higher simply increases CPU usage with no transfer rate increase
    chunksize = 1536
    chunkcount = 0
    totalbytes = 0
    cts = 0
    lastcts = 0
    eofstring = b''+"<<EOF>>\n".encode()
    sleeptime = 0.01
    ctstimeout = 20 # Timeout in seconds
    ctstimeoutcount = 0

    with open(filename,"rb") as readfile:
        while True:

            # Wait for CTS (Clear to Send) to go high
            cts = connection.getCTS()

            if cts == 1:
                ctstimeoutcount = 0
                chunk = readfile.read(chunksize)
                totalbytes += len(chunk)

                if chunk != b'':
                    chunkcount += 1
                    if chunkcount % int((1000 * 1000) / chunksize) == 0: # Status every ~ 1MB
                        logger.info('{:,}. {:,} Bytes Transferred ({:d}%)'.format(chunkcount, totalbytes, int((totalbytes/filesize) * 100)))

                    isinvalidmsg(chunk)
                    connection.write(chunk)
                else:
                    time.sleep(2)
                    logger.info('End of file - writing EOF')
                    connection.write(eofstring) # Send message indicating file transmission complete
                    break
            else:
                #Make sure RTS is on so client know we're trying to send
                connection.setRTS(1)
                ctstimeoutcount += 1
                if ctstimeoutcount > (ctstimeout / sleeptime):
                    raise Exception('Timeout while transferring file. No CTS signal from receiving side for {} seconds.  Ending transfer.'.format(ctstimeout))

            time.sleep(sleeptime)

            lastcts = cts

    return chunkcount, totalbytes

def waitforCTS(connection, writedata, retries, delay, message, endstate):
    '''
    Write the message [writedata] at least once and then until either CTS
     changes to [endstate] or the number of [retries] is exceeded.
     Retries sent every [delay] seconds and [message] printed each retry
    '''
    count = 0

    while True:
        connection.write(writedata)
        count += 1
        time.sleep(delay)

        logger.info(message + ' (attempt {} of {})'.format(count, retries))
        if count >= retries:
            logger.critical('CTS timeout after {} retries of {} seconds ({} seconds)'.format(count, delay, count * delay))
            raise Exception('CTS timeout after {} retries of {} seconds ({} seconds)'.format(count, delay, count * delay))
            return False

        if connection.getCTS() == endstate:
            return True

    return

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

def transferfile(ser, sourcefolder, subfolder, filename):
    '''
    File Transfer Manager
    Handles various handshakes between sender/receiver and
     sending of file name and hash. Calls the function that
     actually sends the file contents
    '''

    filesize = os.path.getsize(os.path.join(sourcefolder, filename))
    hashvalue = filehash(os.path.join(sourcefolder, filename))

    ser.write(filename.encode() + b' ' +  str(filesize).encode() + '\n'.encode())

    waitforCTS(ser, INITSTRING, 5, 6, 'Waiting for file request from client via CTS high, Sending InitString', True)
    waitforCTS(ser, FILESTRING, 5, 3, 'Waiting for filename confirmation from client via CTS low, Sending FileString', False)

    ser.write(os.path.join(subfolder, filename).encode() + ENDFNAMESTRING) # Send filename to client

    starttime = datetime.datetime.now()
    logger.info('File request received - Transferring "{}"'.format(filename))

    chunkcount, totalbytes = sendfiledata(ser, os.path.join(sourcefolder, filename), filesize)
    logger.info('Read {:,} Bytes (in {} chunks) of {:,} Bytes - {:,} Bytes missed'.format(totalbytes, chunkcount, filesize, filesize - totalbytes))
    if filesize - totalbytes != 0:
        logger.warning('Transfer file size mismatch ({:,} Bytes) - Transferred {:,} Bytes\tFile Size {:,} Bytes'.format(filesize - totalbytes, totalbytes, filesize))
    time.sleep(1)

    waitforCTS(ser, ENDSTRING, 5, 2, 'Sending EndString until CTS high', True)

    ser.write(hashvalue.encode())
    logger.info('Sending hash: {}'.format(hashvalue.encode()))

    while True:
        logger.info('Waiting for confirmation from client of successful transfer via DSR low')
        time.sleep(0.5)
        if ser.getDSR() == False:
            break

    if ser.getCTS() == True:
        transferstatus = 1
        logger.info('CTS high - client indicated file received successfully ({}, {})'.format(ser.getCTS(), ser.getDSR()))
    else:
        transferstatus = 0
        logger.critical('!!CTS low - client indicated file corrupted!! ({}, {})'.format(ser.getCTS(), ser.getDSR()))

    endtime = datetime.datetime.now()
    logger.debug('\nSent {:,} Chunks'.format(chunkcount))
    logger.info('Finished @ ' + str(endtime) + '\tElapsed Time: %s ' % (str(endtime - starttime)))
    logger.info('-'*30 + ' End of transfer ' + '-'*30)

    return transferstatus #ser.getCTS()

def cachefile(src, dst, filename):

    folderinit(dst, 'Cache folder')

    try:
        logger.info('Caching file locally: Copying "{}" to "{}"'.format(os.path.join(src, filename), os.path.join(dst, filename)))
        shutil.copy2(os.path.join(src, filename), os.path.join(dst, filename))
    except Exception as e:
        raise

def isinvalidmsg(message):
    '''
    Checks if the provided message contains any of the reserved keywords
    If it does, the transfer is invalide and an exception will be raised
     to restart the main loop
    '''

    invalidmsg = []
    invalidmsg.append(INITSTRING)
    invalidmsg.append(FILESTRING)
    invalidmsg.append(ENDSTRING)

    for msg in invalidmsg:
        if msg in message:
            msg = msg.replace('<<', '')
            msg = msg.replace('>>', '')
            raise InvalidMsgError("Invalid message '{}' found in data.".format(msg))

    return False

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
    pidfile = '/tmp/serial-send-file.pid'

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
            logger.warning('{} ({}) does not exist.  Attempting to create.'.format(diruse, dirname))
            os.makedirs(dirname)
    except Exception as e:
        logger.warning('Exception creating {} ({})\n\tException Message: {}'.format(diruse, dirname, e))

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
            logger.info('Serial port opened successfully. Port Configuration: {}'.format(ser))
            sendmessage(ser, 'Startup - Serial Port {} Opened\n'.format(ser.port).encode())
            return ser
        except Exception as e:
            logger.critical('Exception opening serial port. Retrying...\n\tException Message: {}'.format(e))

            time.sleep(10)

    return ser

def closeserialport(connection):

    print('Closing Comm. Port {}.'.format(connection))
    sendmessage(connection, 'Server send process is shutting down.')

    connection.close()
    logger.info('-'*30 + ' Serial Port closed ' + '-'*30)

    return

def sendmessage(connection, message):
    '''
    Send the message to the specified serial connection
    '''

    try:
        connection.write('SERVER UPDATE: {}'.format(message))
    except Exception as e:
        logger.warning('Exception sending message "{}" to client.\n\tException Message: {}'.format(message, e))

def uploadfile(srcfile, dstfolder):
    '''
    Copy a file to the upload folder
    srcfile: Full source filename including path
    '''

    uploadfile = os.path.join(dstfolder, os.path.basename(srcfile))

    folderinit(dstfolder, 'Upload file destination folder')

    try:
        shutil.copy2(srcfile, uploadfile)
    except Exception as e:
        logger.error('File "{}" could not be copied to upload folder "{}".\n\tException Message: {}'.format(srcfile, dstfolder))

    return

def removeignored(list, root):

    for ignored in IGNOREDFILES:
        if ignored in list:
            list.remove(ignored)
            filename = os.path.join(root, ignored)
            logger.info("File '{}' is in the ignore list and will not be transferred. Deleting '{}'.".format(ignored, filename))

            try:
                os.remove(filename)
            except Exception as e:
                logger.warning("Exception deleting file '{}'.\n\tException Message: {}".format(filename, e))

    return list

def main():
    '''
    Transfer flow

    Server --> Send InitString until CTS goes high
    Sets RTS high when InitString received <-- Client

    Server --> Send FileString until CTS goes low
    Sets RTS low when InitString received <-- Client

    Server --> Send filename
    Sets RTS high when filename received <-- Client

    Server --> Send file when CTS goes high
        Server <--> Client toggle CTS/RTS during transfer for flow control
    Sets RTS high when InitString received <-- Client

    Server --> Send EndString until CTS goes high
    Sets RTS high when EndString received <-- Client

    Server --> Send file hash
    Sets RTS low and DTR high when hash received / comparing with local (received) file hash <-- Client
    Sets DTR low when compare complete and sets RTS based on whether local/remote hashes match (0 = fail, 1 = success) <-- Client

    Server --> Prints success / fail message based on RTS after DSR turns back off

    The RTS/DTR (Client) -> CTS/DSR (Server) process in the last step is due to
      RTS/DTR turning on when the connection is closed

    '''

    transfercount = {}

    folderinit(LOGFILEDIR, 'LOGFILEDIR')
    configure_logging()

    logger.info('-'*30 + ' Data Diode Send Process Starting ' + '-'*30)

    if os.getuid() != 0:
        print('Cannot run as a normal user. Root access required to open the serial port - try calling via sudo.')
        logger.critical('Cannot run as a normal user. Root access required to open the serial port - try calling via sudo.')
        sys.exit()

    pid, pidfile  = getpid()
    atexit.register(removepid, pidfile=pidfile, pid=pid)

    folderinit(CACHEDIR, 'CACHEDIR')

    ser = openserialport()

    if os.path.isdir(ROOT) == False:
        logger.warning('Root folder "{}" not found.  Shared folder may not be mounted.'.format(ROOT))
        sendmessage(ser, 'Root folder "{}" not found.  Shared folder may not be mounted.'.format(ROOT))
    elif os.path.isdir(SRCDIR) == False:
        logger.warning('Source folder "{}" not found.'.format(SRCDIR))
        sendmessage(ser, 'Source folder "{}" not found.'.format(SRCDIR))

    while True:

        if ser.isOpen() == False:
            try:
                logger.warning('Serial port no longer open. Attempting to re-open.')
                ser.open()
                logger.info('Serial port re-opened successfully. Port Configuration: {}'.format(ser))

            except Exception as e:
                logger.critical('Exception opening serial port. Retrying...\n\tException Message: {}'.format(e))


        try:
            ser.setDTR(0) # Indicate transmission possible / in progress
            time.sleep(1)
            ser.write(SERVERALIVESTRING)

            logger.debug('-'*30 + ' Checking for files ' + '-'*30)

            logger.debug(SRCDIR)
            if os.path.exists(ROOT):
                transfercount['successful'] = 0
                transfercount['failed'] = 0

                for root, dirs, files in os.walk(SRCDIR):
                    logger.debug('Processing Directory(s)... \n\t%s' % (dirs))
                    if files: logger.info('Processing file(s) in "{}": {}.'.format(root, files))

                    files = removeignored(files, root)

                    for f in files:
                        filename = os.path.normpath(f)
                        folder = root.replace(SRCDIR, '')
                        source = os.path.join(root, f)

                        if len(folder) > 0:
                            folder = folder[1::] # Strip off leading "/"

                        cache = os.path.normpath(os.path.join(CACHEDIR, folder))
                        cachefile(root, cache, filename)

                        logger.debug('Sending {}.'.format(os.path.normpath(f)))
                        result = transferfile(ser, cache, folder, filename)

                        # When using full path, shutil.move will overwrite the destination file if present
                        if result == True:
                            transfercount['successful'] += 1

                            destination = os.path.join(root, DONEDIR, folder, f)
                            logger.info('Moving file to "{}".'.format(destination))
                            folderinit(os.path.join(root, DONEDIR, folder), 'Transferred subfolder')
                            shutil.move(os.path.abspath(source), os.path.abspath(destination))
                        else:
                            transfercount['failed'] += 1

                            destination = os.path.join(root, FAILDIR, folder, f)
                            logger.info('Moving file to "{}".'.format(destination))
                            folderinit(os.path.join(root, FAILDIR, folder), 'Failed subfolder')
                            shutil.move(os.path.abspath(source), os.path.abspath(destination))

                        logger.info('Deleting cached file "{}".'.format(os.path.join(cache, filename)))
                        os.remove(os.path.join(cache, filename))

                        time.sleep(1)

                if transfercount['successful'] + transfercount['failed'] > 0:
                    if transfercount['failed'] > 0 or transfercount['successful'] > 1:
                        uploadfile(LOGFILENAME, os.path.join(SRCDIR, 'logs'))
                        pass
                    logger.info('Transfer(s) complete ({} successful, {} failed).'.format(transfercount['successful'], transfercount['failed']))
                    logger.info('-'*30 + ' Restarting main loop ' + '-'*30 + '\n')

            else:
                logger.warning('Root folder "{}" not found.  Shared folder may not be mounted.'.format(ROOT))
                sendmessage(ser, 'Root folder "{}" not found.  Shared folder may not be mounted.'.format(ROOT))

        except InvalidMsgError as e:
            logger.error('InvalidMsgError. {}'.format(e))

            try:
                destination = os.path.join(root, FAILDIR, folder, f)
                logger.info('Moving file to "{}"'.format(destination))
                folderinit(os.path.join(root, FAILDIR, folder), 'Transferred subfolder')
                shutil.move(os.path.abspath(source), os.path.abspath(destination))
            except:
                logger.critical("Unable to move file '{}' to '{}'".format(f, destination))

        except KeyboardInterrupt as e:
            logger.warning('Keyboard Interrupt. Exiting program...\n\tException Message: {}'.format(e))
            break

        except Exception as e:
            logger.critical('Exception in main loop.  Restarting...\n\tException Message: {}'.format(e))

        time.sleep(15)


if __name__ == '__main__':
    main()
