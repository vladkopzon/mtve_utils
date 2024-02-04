#!/usr/bin/env python3

import os
import sys
import stat
import pwd
import fileinput
import time
import fcntl
import logging
import getpass
import signal
import hjson

mtv_lib   = os.getenv('MTV_LIB', "")
crun_envdir = os.getenv('CRUN_ENVDIR', "")
sys.path.append(mtv_lib + "/" + crun_envdir)

from mtve_headers import *

class REL_MODE(Enum):
    NORMAL     = 0          # normal release operation
    FORCE      = 1          # Force release by root
    INTERRUPT  = 2          # release when parent process got SIGINT/TERM
    USERMODE   = 3          # user manual head release (error scenario)


class FpgaSemaphore:


    def __init__(self, queue_file):
        self.queue_file = queue_file
        self.logfile    = str(queue_file) + '.log'
        self.id     = None
        self.locked = False
        self.abort  = False
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        
        if not os.path.isfile(self.queue_file):
            raise FileNotFoundError(f"Job execution queue file [{self.queue_file}] does not exist!")


    def remove_id(self, id, mode=REL_MODE.NORMAL):
        id_to_return = id
        removed = False
        try:
            with open(self.queue_file, 'r') as f:
                lines = f.readlines()

            with open(self.queue_file, 'w') as f:
                for i, line in enumerate(lines):
                    line = line.rstrip('\n')
                    if i == 0:
                        if mode == REL_MODE.FORCE \
                           or (mode == REL_MODE.NORMAL and line == id) \
                           or (mode == REL_MODE.INTERRUPT and line == id) \
                           or (mode == REL_MODE.USERMODE and self.is_userline(line)):
                            id_to_return = line
                            removed = True
                        else:
                            print(line, file=f)
                    elif mode == REL_MODE.INTERRUPT and line == id:
                        id_to_return = line
                        removed = True
                    else:
                        print(line, file=f)

        except Exception as e:
            self.logger.critical(f"An error occurred while removing the first line: {e}")

        if removed:
            return id_to_return
        else:
            return False


    def is_userline(self, line):
        job_entry = hjson.loads(line)
        if isinstance(job_entry, dict):
            if job_entry.get('user', False) == getpass.getuser():
                return True
        return False
                            
    
    def get(self, id, max_iterations=10, sleep_time=5):
        try:
            # Append the id without a lock
            saved_umask = os.umask(0)
            os.umask(MTVE_GLOBALS.SHARED_FILE_PERMISSIONS)
            with open(self.queue_file, 'a') as f:
                f.write(repr(id) + '\n')
            self.logger.info(f'My ID [{id}] added to execution queue: [{self.queue_file}]')
            self.id = id
            
            i = 0
            while not self.abort:
                # Check the first line without a lock
                with open(self.queue_file, 'r') as f:
                    first_line = f.readline().strip()
                    job_count = sum(1 for line in f)
                    if first_line == repr(id):
                        # If the first line is the id we just added, queue is empty. Execute it...
                        self.logger.info(f'FPGA platform is free. Start execution [{id}]...')
                        with open(self.logfile, 'a') as logfile:
                            logfile.write(f'["locked", {id}],\n')
                        self.locked = True
                        break
                    else:
                        # If the first line is not the id we just added, wait...
                        if i==0:
                            with open(self.logfile, 'a') as logfile:
                                logfile.write(f'["queued", {id}],\n')
                        self.logger.info(f'Waiting for [{job_count}] job(s) to complete. sleeping {i}:{sleep_time}')
                        self.logger.info('Waiting job list:')
                        self.logger.info(first_line)
                        for line in f:
                            self.logger.info(line.strip())
                        time.sleep(sleep_time)
                        i += 1
        except Exception as e:
            self.logger.critical(f"An error occurred while getting semaphore: {e}")
            
        os.umask(saved_umask)
        if i == max_iterations-1:
            return False
        else: return True

        
    def release(self, id=None, release_msg=None, mode=REL_MODE.NORMAL):
        job = id
        user = getpass.getuser()
        saved_umask = os.umask(0)
        os.umask(MTVE_GLOBALS.SHARED_FILE_PERMISSIONS)
        try:
            # Lock the file to remove the id
            with open(self.queue_file, 'r+') as f:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                job = self.remove_id(id=repr(id), mode=mode)
                fcntl.flock(f, fcntl.LOCK_UN)
                self.locked = False
                cmd = 'unlock'
                if mode == REL_MODE.FORCE:
                    self.logger.info(f'Force release of [{job}] by {user}: [{self.queue_file}]')
                    #id = f"{user}:{job}"
                    cmd = 'force_unlock'
                elif mode == REL_MODE.INTERRUPT:
                    self.logger.info(f'Release on TERM/INT of [{job}] by {user}: [{self.queue_file}]')
                    #id = f"{user}:{job}"
                    cmd = 'killed'
                else:
                    self.logger.info(f'Job [{job}] released from execution queue: [{self.queue_file}]')
                    if mode == REL_MODE.USERMODE:
                        cmd = 'dequeue'
                        release_msg = job
                with open(self.logfile, 'a') as f:
                    if job:
                        f.write(f'["{cmd}", {release_msg}],\n')
                    else:
                        if not id:
                            id = 'ASSERTION!!! id == None'
                        f.write(f'["unlock_error", "{id}"],\n')
                        
        except Exception as e:
            self.logger.critical(f"An error occurred while releasing semaphore: [{id}] {e}")
        
        os.umask(saved_umask)
        return job

    
    def dequeue(self, interrupt=False):
        self.abort = True
        if interrupt:
            status = self.release(id=self.id, release_msg=self.id, mode=REL_MODE.INTERRUPT)
        else:
            status = self.release(release_msg='dequeue', mode=REL_MODE.USERMODE)

        if status:
            status = 'Ok'
        return (f'Semaphore: good to go! interrupt={interrupt}, status=[{status}]')

    
################################################################################
if __name__ == "__main__":

    from multiprocessing import Process
    from pathlib import Path
    from datetime import datetime

    import argparse
    logging.basicConfig(format='%(levelname)s - %(module)s.%(funcName)s - %(message)s')
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument('-queue', type=str, required=True,
                        help='Specifies queue filename')
    parser.add_argument('-jobs', type=int, default=1,
                        help='Specifies how many jobs to pull from queue')
    parser.add_argument('-restart', action='store_true',
                        help='Restart the queue')

    parser.add_argument('-dev' ,  action='store_true',
                        help='For script development only')

    args = parser.parse_args()

    def test_semaphore(semaphore, id):
        if semaphore.get(id):
            semaphore.release(id)
        else:
            logger.error(f'Unable to get semaphore [{id}]')

    #in MTVe env quename should be: MTVE_GLOBALS.FPGA_QUEUE_DIR / MTVE_GLOBALS.FPGA_QUEUE_BASE_NAME + uniq extention per machine
    semaphore = FpgaSemaphore(queue_file=args.queue)

    if args.restart:
        pass
    if args.jobs:
        user = getpass.getuser()
        now = datetime.now()
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        msg = {'user':user, 'time':time_str}
        for i in range(args.jobs):
            job = semaphore.release(release_msg=msg, mode=REL_MODE.FORCE)

    if args.dev:
        # Create and start multiple processes
        processes = []

        # p = Process(target=semaphore.get, args=('55',)) # block queue
        # p.start()
        # processes.append(p)

        for i in range(3):
            p = Process(target=test_semaphore, args=(semaphore, f"{i}"))
            p.start()
            processes.append(p)

        # Wait for all processes to finish
        for p in processes:
            p.join()
