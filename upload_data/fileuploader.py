#!/usr/bin/env python
"""Upload the contents of the designated source folder to Dropbox and post a notification w/ url to slack.
Based on the Dropbox example app for API v2.
"""

from __future__ import print_function

import argparse
import contextlib
import datetime
import os
import six
import sys
import time
import unicodedata
import shutil
import logging
from logging.handlers import RotatingFileHandler
import requests.packages.urllib3
import signal
import configparser
import subprocess

if sys.version.startswith('2'):
    input = raw_input

import dropbox
from dropbox.files import FileMetadata, FolderMetadata
from slacker import Slacker

PROJECTNAME = '' # Project name loaded from config file
SLACKBOTNAME = '' # Loaded from config file

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)
#logger.setLevel(logging.WARNING)
formatter = logging.Formatter('%(asctime)s\t%(funcName)s\t%(levelname)s\t%(message)s')

# Console logging
ch = logging.StreamHandler()#sys.stdout)
ch.setFormatter(formatter)
logger.addHandler(ch)

# File logging (Rotating)
rfh = RotatingFileHandler('/var/lib/sierra/log-fileuploader.txt', maxBytes=512000, backupCount=5)
rfh.setFormatter(formatter)
logger.addHandler(rfh)


def main(slack, localuploadsource, dropboxtoken, slacktoken, slackchannel):
    """Main program.
    Parse command line, then iterate over files and directories under
    rootdir and upload all files.  Skips some temporary files and
    directories, and avoids duplicate uploads by comparing size and
    mtime with the server.
    """

    folder = os.path.join(PROJECTNAME, 'incoming')
    rootdir = localuploadsource

    logger.debug('Dropbox folder name: {}'.format(folder))
    logger.debug('Local directory: {}'.format(rootdir))
    if not os.path.exists(rootdir):
        logger.warning('{} does not exist on your filesystem'.format(rootdir))
        folderinit(rootdir, 'Upload folder')
        sys.exit(1)
    elif not os.path.isdir(rootdir):
        logger.warning('{} is not a folder on your filesystem'.format(rootdir))
        sys.exit(1)

    dbx = dropbox.Dropbox(dropboxtoken)
    #slack = Slacker(slacktoken)

    for dn, dirs, files in os.walk(rootdir):
        subfolder = dn[len(rootdir):].strip(os.path.sep)
        listing = list_folder(dbx, folder, subfolder)
        logger.debug('Descending into {} ...'.format(subfolder))

        # First do all the files.
        for name in files:
            fullname = os.path.join(dn, name)
            if not isinstance(name, six.text_type):
                name = name.decode('utf-8')
            nname = unicodedata.normalize('NFC', name)
            if name.startswith('.'):
                print('Skipping dot file:', name)
            elif name.startswith('@') or name.endswith('~'):
                print('Skipping temporary file:', name)
            elif name.endswith('.pyc') or name.endswith('.pyo'):
                print('Skipping generated file:', name)
            elif nname in listing:
                # Probably will just want to force overwrite and not bother checking
                md = listing[nname]
                mtime = os.path.getmtime(fullname)
                mtime_dt = datetime.datetime(*time.gmtime(mtime)[:6])
                size = os.path.getsize(fullname)
                if (isinstance(md, dropbox.files.FileMetadata) and
                    mtime_dt == md.client_modified and size == md.size):
                    logger.info('{} is already synced [stats match]'.format(name))
                    deletefile(fullname)
                else:
                    logger.info('{} exists with different stats, downloading'.format(name))
                    res = download(dbx, folder, subfolder, name)
                    with open(fullname) as f:
                        data = f.read()
                    if res == data:
                        logger.info('{} is already synced [content match]'.format(name))
                        deletefile(fullname)
                    else:
                        logger.info('{} has changed since last sync'.format(name))
                        

                        if True: #yesno('Refresh %s' % name, False, args): # Force overwrite
                            upload(dbx, fullname, folder, subfolder, name, overwrite=True)
                            shareurl = getshareurl(dbx, folder, subfolder)
                            deletefile(fullname)
                            postslackmsg(slack, '{}'.format(slackchannel), ' uploaded *{}* to Dropbox folder (_<{}|{}>_)'.format(os.path.basename(fullname), shareurl, '/{}/{}'.format(folder, subfolder)), True)

            elif True: #yesno('Upload %s' % name, True, args): #Automatically upload new files
                upload(dbx, fullname, folder, subfolder, name)
                deletefile(fullname)
                shareurl = getshareurl(dbx, folder, subfolder)
                postslackmsg(slack, '{}'.format(slackchannel), ' uploaded *{}* to Dropbox folder (_<{}|{}>_)'.format(os.path.basename(fullname), shareurl, '/{}/{}'.format(folder, subfolder)), True)

        # Then choose which subdirectories to traverse.
        keep = []
        for name in dirs:
            if name.startswith('.'):
                print('Skipping dot directory:', name)
            elif name.startswith('@') or name.endswith('~'):
                print('Skipping temporary directory:', name)
            elif name == '__pycache__':
                print('Skipping generated directory:', name)
            else: # yesno('Descend into %s' % name, True, args):
                #print('Keeping directory:', name)
                keep.append(name)
            #else:
                #print('OK, skipping directory:', name)
        dirs[:] = keep


def deletefile(fullname):
    logger.info('Deleting uploaded file "{}"'.format(fullname))
    
    try:
        os.remove(fullname)
    except:
        logger.warning('Unable to delete file "{}"'.format(fullname))

    pass

def postslackmsg(obj, channel, message, pname=True):
    '''
    Posts a message to the provided Slack channel as a bot
    The message defaults to including a prepended Project name (PROJECTNAME)
     as long as the pname argument is True
    '''

    botname = SLACKBOTNAME
    try:
        if pname == True:
            obj.chat.post_message(channel, '*Project* *_{}_*: {}'.format(PROJECTNAME, message), username=botname, as_user=False) #True)
        else:
            obj.chat.post_message(channel, '{}'.format(message), username=botname, as_user=False) #True)  
    except Exception as e:
        logger.warning('Slack message post failed ({}).\n\tException Message: {}'.format(message, e))

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
    pidfile = '/tmp/fileuploader.pid'

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
    except Exception as e:
        logger.critical('Exception creating {} ({}\n\tException Message: {}'.format(diruse, dirname, e))

    return

def getconfig(configfile):
    '''
    Read parameters from the config file and return them
    '''

    if os.path.isfile(configfile):
    
        try:
            config = configparser.ConfigParser()
            config.read(configfile)

            projectname = config['Project']['Name']
            uploadsource = config['Project']['UploadSrc'] 
            dropboxtoken = config['Dropbox']['Token'] # See https://www.dropbox.com/developers/apps
            slacktoken = config['Slack']['Token'] # See https://api.slack.com/web
            slackchannel = (config['Slack']['Channel']).lower()
            slackbotname = config['Slack']['Botname']

            return projectname, uploadsource, dropboxtoken, slacktoken, slackchannel, slackbotname

        except Exception as e:
            logger.critical('Exception reading config file "{}".  Exception Message: {}'.format(configfile, e))

    else:
        raise Exception('Config file "{}" does not exist.'.format(configfile))

    return #projectname, uploadsource, dropboxtoken, slacktoken, slackchannel

def getshareurl(dbx, folder, subfolder):
    '''
    Create a share URL for the requested Dropbox folder and return it
    '''

    dbxfolder = '/{}/{}'.format(folder, subfolder)
    dbxfolder = dbxfolder.rstrip('/')
    try:
        share = dbx.sharing_create_shared_link(dbxfolder, short_url=True, pending_upload=None)
    except Exception as e:
        logger.critical('Exception getting share link {} ({}\n\tException Message: {}'.format(diruse, dirname, e))
        return ''
    else:
        return share.url

def check_for_cmd(slack, localuploadsource, dropboxtoken, slacktoken, slackchannel):
    '''
    Check Cloud drive for commands to run
    If a command file is found, delete it from the cloud and throw an exception if it fails
     (to prevent an infinite loop if the command file remains there)
    Parse the file to check for a valid command keyword and get the command to execute
     if valid command keyword found (this prevents passing of arbitrary commands).
    Execute the command
    Uploads a response file to Dropbox to report exceptions or success.
    '''

    folder = os.path.join(PROJECTNAME, 'commands')
    subfolder = ''
    filename = 'command.txt'
    response = 'command_response.txt'
    path = os.path.join('/', folder, subfolder, filename)
    res = os.path.join(os.path.dirname(os.path.realpath(__file__)), response) #'/opt/sierra/data_diode/upload_data'

    write_response_file(response, 'w', 'Command Check Starting\n')
    dbx = dropbox.Dropbox(dropboxtoken)

    try:
        cmd = download(dbx, folder, subfolder, filename)
        logger.info('Command file "{}" containing command "{}" found on cloud drive. Attempting to delete...'.format(path, cmd))
        write_response_file(response, 'a', 'Command received: \t{}\n'.format(cmd))
    except Exception as e:
        logger.debug('Command file "{}" not found.'.format(path))
        write_response_file(response, 'a', 'Command exception\t{}\n'.format(e))
        return

    try:
        delete_cloud_file(dbx, path)
        write_response_file(response, 'a', 'Command file deleted: \t{}\n'.format(path))
    except Exception as e:
        logger.error('Command file "{}" could not be deleted. Command will not be processed.'.format(path))
        write_response_file(response, 'a', 'Command exception\t{}\n'.format(e))
        upload(dbx, res, folder, subfolder, response, overwrite=True)
        raise

    # Only process commands if the command file from the cloud can be deleted.
    # Otherwise an infinite loop could be created
    logger.info('Processing command request "{}" ...'.format(path, cmd))

    try:
        parsed_cmd = parse_cmd(cmd, slack, slackchannel)
    except Exception as e:
        write_response_file(response, 'a', 'Command exception\t{}\n'.format(e))
        upload(dbx, res, folder, subfolder, response, overwrite=True)
        raise

    write_response_file(response, 'a', 'Running command: \t{}\n'.format(parsed_cmd))

    # Copy file to upload folder
    try:
        upload(dbx, res, folder, subfolder, response, overwrite=True)
    except Exception as e:
        pass

    # Run command
    try:
        exitcode = subprocess.call(parsed_cmd)

        if exitcode == 0:
            msg = 'Command "{}" completed successfully (return code = {}).'.format(parsed_cmd, exitcode)
        else:
            msg = 'Command "{}" failed (return code = {}).'.format(parsed_cmd, exitcode)

        write_response_file(response, 'a', '{}'.format(msg))
        logger.info(msg)
        postslackmsg(slack, '{}'.format(slackchannel), '{}'.format(msg), True)
        upload(dbx, res, folder, subfolder, response, overwrite=True)

    except Exception as e:
        postslackmsg(slack, '{}'.format(slackchannel), 'Exception running *{}* command "{}"'.format(cmd, parsed_cmd), True)
        raise

    return

def write_response_file(outputfile, filemode, filecontent):
    '''
    Writes data to a file (either append or write) with a timestamp
    '''

    try:
        with open(outputfile, filemode) as file:
            file.write('{}\t{}'.format(datetime.datetime.now(), filecontent))
    except Exception as e:
        raise

def delete_cloud_file(dbx, path):
    
    try:
        dbx.files_delete(path)
    except Exception as e:
        raise

    logger.info('Deleted cloud file "{}".'.format(path))

    return

def parse_cmd(command, slack, slackchannel):
    '''
    Parse the received command and return a list to be executed via the subprocess module
    Also attempts to post a message to slack regarding

    Commands:
      reboot_external - Reboot the external (internet connected) Pi
      reboot_internal - Reboot the internal (secure network) Pi - not implemented
      get_external_logs - Copies log files to the upload folder by running the daily_log_upload script
      noop - No Operation (way to verify feedback without doing anything)
    '''

    msg = 'Command received: *{}*.'.format(command)
    command = command.lower()

    if command == "reboot_external":
        msg = '{}\t{}'.format(msg, 'Rebooting external Pi. Here goes nothing...'.format(command))
        parsed_cmd =  ["sudo", "/sbin/reboot"]

    elif command == "reboot_internal":
        msg = '{}\t{}'.format(msg, 'Rebooting internal (secure) Pi. Here goes nothing...'.format(command))
        parsed_cmd = ['/opt/sierra/data_diode/scripts/reboot_internal.sh'] # TBD via script/GPIO

    elif command == "get_external_logs":
        msg = '{}\t{}'.format(msg, 'Copying external Pi logs to upload folder.'.format(command))
        parsed_cmd = ['/opt/sierra/data_diode/transfer_data/scripts/daily_log_upload']

    elif command == "noop":
        msg = '{}\t{}'.format(msg, 'Running noop command (clear).'.format(command))
        parsed_cmd = ['clear']

    else:
        msg = '{}\t{}'.format(msg, '*Warning*: Invalid command.'.format(command))
        postslackmsg(slack, '{}'.format(slackchannel), '{}'.format(msg), True)
        raise Exception('Invalid command "{}" provided. No action taken.'.format(command))

    try:
        postslackmsg(slack, '{}'.format(slackchannel), '{}'.format(msg), True)
    except:
        pass

    logger.warning(msg)

    return parsed_cmd

def list_folder(dbx, folder, subfolder):
    """List a folder.
    Return a dict mapping unicode filenames to
    FileMetadata|FolderMetadata entries.
    """
    path = '/%s/%s' % (folder, subfolder.replace(os.path.sep, '/'))
    while '//' in path:
        path = path.replace('//', '/')
    path = path.rstrip('/')
    try:
        with stopwatch('list_folder'):
            res = dbx.files_list_folder(path)
    except dropbox.exceptions.ApiError as err:
        logger.debug('Folder listing failed for {} -- assumped empty: {}'.format(path, err))
        return {}
    else:
        rv = {}
        for entry in res.entries:
            rv[entry.name] = entry
        return rv

def download(dbx, folder, subfolder, name):
    """Download a file.
    Return the bytes of the file, or None if it doesn't exist.
    """
    path = '/%s/%s/%s' % (folder, subfolder.replace(os.path.sep, '/'), name)
    while '//' in path:
        path = path.replace('//', '/')
    with stopwatch('download'):
        try:
            md, res = dbx.files_download(path)
        except dropbox.exceptions.HttpError as err:
            logger.warning('*** HTTP error: {}'.format(err))
            return None
    data = res.content
    logger.debug('File size: {} bytes;\tFile metadata: {}'.format(len(data), md))
    return data

def upload(dbx, fullname, folder, subfolder, name, overwrite=False):
    """Upload a file.
    Return the request response, or None in case of error.
    """
    path = '/%s/%s/%s' % (folder, subfolder.replace(os.path.sep, '/'), name)
    while '//' in path:
        path = path.replace('//', '/')
    mode = (dropbox.files.WriteMode.overwrite
            if overwrite
            else dropbox.files.WriteMode.add)
    mtime = os.path.getmtime(fullname)
    with open(fullname, 'rb') as f:
        data = f.read()
    with stopwatch('upload %d bytes' % len(data)):
        try:
            res = dbx.files_upload(
                data, path, mode,
                client_modified=datetime.datetime(*time.gmtime(mtime)[:6]),
                mute=True)
        except dropbox.exceptions.ApiError as err:
            logger.warning('*** API error: {}'.format(err))
            return None
    logger.info('Uploaded as {}'.format(res.name.encode('utf8')))
    return res

def yesno(message, default, args):
    """Handy helper function to ask a yes/no question.
    Command line arguments --yes or --no force the answer;
    --default to force the default answer.
    Otherwise a blank line returns the default, and answering
    y/yes or n/no returns True or False.
    Retry on unrecognized answer.
    Special answers:
    - q or quit exits the program
    - p or pdb invokes the debugger
    """
    if args.default:
        print(message + '? [auto]', 'Y' if default else 'N')
        return default
    if args.yes:
        print(message + '? [auto] YES')
        return True
    if args.no:
        print(message + '? [auto] NO')
        return False
    if default:
        message += '? [Y/n] '
    else:
        message += '? [N/y] '
    while True:
        answer = input(message).strip().lower()
        if not answer:
            return default
        if answer in ('y', 'yes'):
            return True
        if answer in ('n', 'no'):
            return False
        if answer in ('q', 'quit'):
            print('Exit')
            raise SystemExit(0)
        if answer in ('p', 'pdb'):
            import pdb
            pdb.set_trace()
        print('Please answer YES or NO.')

@contextlib.contextmanager
def stopwatch(message):
    """Context manager to print how long a block of code took."""
    t0 = time.time()
    try:
        yield
    finally:
        t1 = time.time()
        #print('Total elapsed time for %s: %.3f' % (message, t1 - t0))

if __name__ == '__main__':

    pid, pidfile  = getpid()
    delay = 60
    configfile = '/opt/sierra/data_diode/upload_data/fileuploader.cfg'

    logger.info('File Uploader starting with PID {}.  {} second delay between scans.'.format(pid, delay))

    while True:
        try:
            PROJECTNAME, localuploadsource, dropboxtoken, slacktoken, slackchannel, SLACKBOTNAME = getconfig(configfile)
            logger.info('Config file "{}" read successfully.'.format(configfile))
            logger.info('Project name: "{}", Upload Source: "{}", Slack channel: "{}", Slack Bot: "{}"'.format(PROJECTNAME, localuploadsource, slackchannel, SLACKBOTNAME))
            if slackchannel[0] != '#':
                logger.warning('Slack channel: "{}" may need to start with "#" to work properly. Prepending "#" on channel name.'.format(slackchannel))
                slackchannel = '#{}'.format(slackchannel)
            break

        except Exception as e:
            print('Exception reading config file "{}".  Retrying in {} seconds.  Exception Message: {}'.format(configfile, delay, e))
            logger.critical('Exception reading config file "{}".  Retrying in {} seconds.  Exception Message: {}'.format(configfile, delay, e))

        time.sleep(delay)

    slack = Slacker(slacktoken)
    slack.chat.post_message(slackchannel, '*File Uploader starting with parameters:*\n\tProject name: *_{}_*\n\tUpload Source: *_{}_*'.format(PROJECTNAME, localuploadsource, slackchannel), SLACKBOTNAME)

    while True:
        try:
            main(slack, localuploadsource, dropboxtoken, slacktoken, slackchannel)
            check_for_cmd(slack, localuploadsource, dropboxtoken, slacktoken, slackchannel)

        except KeyboardInterrupt as e:
            logger.warning('Keyboard Interrupt. Exiting program...\n\tException Message: {}'.format(e))        
            os.unlink(pidfile)
            break
        
        except Exception as e:
            logger.critical('Exception in main loop. Restarting...\n\tException Message: {}'.format(e))
            if e.args[1].args[0].errno == errno.ECONNRESET:
                logger.critical('ECONNRESET - exiting program')
                break
            
        time.sleep(delay)

    os.unlink(pidfile)
    slack.chat.post_message(slackchannel, 'File Uploader stopping.')
