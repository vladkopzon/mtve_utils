#!/usr/bin/env python3

from multiprocessing.connection import Listener
import pickle
import subprocess

print ("Starting NVM burner deamon", flush=True)

TCP_PORT = 53533
AUTH_KEY = b'NVM secret password :)'
BURN_CMD = ['echo', '   burn_command -nvm_image ']

server = Listener(('0.0.0.0', TCP_PORT), authkey=AUTH_KEY)
running = True

while running:
    conn = server.accept()
    print("connection accepted from", server.last_accepted, flush=True)
    while True:
        msg = conn.recv()
        if msg == 'close connection':
            conn.close()
            break
        if msg == 'close server':
            conn.close()
            running = False
            print("Server shutdown from client")
            break

        # otherwise burn NVM
        
        item = pickle.loads(msg)
        shell_cmd = BURN_CMD + [item['nvm_image']]
        #print (shell_cmd, flush=True)
        process = subprocess.Popen(shell_cmd)
        process.wait()
        print (f"Executed with status [{process.returncode}].", flush=True)
        conn.send(process.returncode)
        
server.close()
f.close()
