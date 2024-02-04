import os
import socket
import struct
import array
import time
import logging

from mtv.py.mtv_imports import *

class mmi_connector(object):

    def __init__(self, mtv=None, host='127.0.0.1', port=2300, mmi64=True):
        self.mtv    = mtv
        self.HOST = host
        self.PORT = port
        if os.environ.get('MTVE_SOCKET_TYPE') == 'TCP_SOCKET':
            self.SOCKET_TYPE = socket.AF_INET
            socket_info = str(port) + '@' + host
        else:
            self.SOCKET_TYPE = socket.AF_UNIX
            self.SOCKET_PATH = MTVE_GLOBALS.SOCKET_FNAME \
                + os.environ.get('CRUN_MTV_SOCKET_NAME', MTVE_GLOBALS.SOCKET_UNNAMED)
            socket_info = self.SOCKET_PATH
        #self.TIMEOUT = 10
        self.sleep_time  = 2
        self.sleep_iters = 5
        self.msg_count   = 1
        self.t1          = 0
        self.abs_start   = 0
        
        self._dsize = 8
        self.xtors_max_count = 16
        self._xtor_id_size = 4
        self._mmi64 = mmi64
        self.wait_for_write_ack = False
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG) # DEBUG/ERROR
        if mmi64:
            connected = False
            self.logger.info ("Connecting to socket: [%s]" % (socket_info))
            self.client_socket = socket.socket(self.SOCKET_TYPE, socket.SOCK_STREAM)
            #self.client_socket.settimeout(self.TIMEOUT)
            while self.sleep_iters:
                try:
                    if self.SOCKET_TYPE == socket.AF_INET:
                        self.client_socket.connect((self.HOST, self.PORT))
                    else:
                        time.sleep(3) # to give a chance for C-side :)
                        self.client_socket.connect(self.SOCKET_PATH)
                    self.logger.info ("Successfully connected to the socket")
                    connected = True
                    break
                except socket.error as e:
                    self.logger.debug ("Unable to connect: %s" % e)
                self.sleep_iters -= 1
                self.logger.debug ("Waiting for socket (server not ready yet) [%d]" % self.sleep_iters)
                time.sleep(self.sleep_time)
            if not connected:
                self.logger.critical ("Unable to connect! Exiting...")
                exit()
        return

    def send_msg(self, array_data):
        t1 = self.get_time_us()
        # Pack the array data into a byte stream
        #array_data = [len(array_data)] + array_data
        opcode = array_data[MTVE_GLOBALS.MMI_OPCODE_IDX]
        data_array_to_send = array_data.copy()
        #data_array_to_send[MTVE_GLOBALS.MMI_OPCODE_IDX] |= 1 << MTVE_GLOBALS.MMI_OPCODE_NO_PRINT_MASK
        data_array_to_send = [len(array_data)] + data_array_to_send
        data_bytes = struct.pack('!{}Q'.format(len(data_array_to_send)), *data_array_to_send)
        response_data = [0] # empty response
        # Send the array data over the socket
        if self._mmi64:
            self.client_socket.sendall(data_bytes)
            t2 = self.get_time_us()
            self.logger.debug ("Message sent[%d]: %s" %
                               (self.msg_count, ['0x' + format(value,'X') for value in data_array_to_send]))
        else:
            self.logger.debug ("Message sent[%d] (mmi64=False): %s" %
                               (self.msg_count, ['0x' + format(value,'X') for value in data_array_to_send]))

                
        self.logger.info(f'OPCODE: [{MTVE_GLOBALS.MMI_OPCODE_IDX}] {opcode}')
        if opcode == MTVE_GLOBALS.MMI_OPCODES.REGIF_READ.value:
            length = array_data[MTVE_GLOBALS.MMI_LENGTH_IDX]
            if self._mmi64:
                self.logger.debug ("waiting for mmi config read response...")
                response_bytes = self.client_socket.recv(length*self._dsize)
                #self.logger.debug('RESP_BYTES:[%s]', response_bytes)
                num_elements  = len(response_bytes) // 8
                response_data = array.array('Q', struct.unpack('<' + 'Q' * num_elements, response_bytes))
                self.logger.debug('Got response[%d]: %s' %
                                  (self.msg_count, ['0x' + format(value,'X') for value in response_data]))
            else:
                if self.msg_count > 1000:
                    response_data = [0x0]
                else:
                    response_data = [self.msg_count] * length
                    #response_data = [0x0000000400000000 + self.msg_count] * length
                    #response_data = [0x4000400000000020 + self.msg_count] * length
                    self.logger.debug('Responding with dummy data (mmi64=False): %s' %
                                       ['0x' + format(value,'X') for value in response_data])
            t3 = self.get_time_us()

        elif opcode == MTVE_GLOBALS.MMI_OPCODES.REGIF_WRITE.value:
            if self.wait_for_write_ack:
                self.logger.debug ("waiting for mmi config write ACK...")
                if self._mmi64:
                    response_bytes = self.client_socket.recv(self._dsize)
                    self.logger.debug('Got write ACK[%d]' % self.msg_count)
            t3 = self.get_time_us()

        elif opcode == MTVE_GLOBALS.MMI_OPCODES.SCAN.value:
            if self._mmi64:
                self.logger.debug ("waiting for mmi scan response...")
                # Receive the response from the server
                response_bytes = self.client_socket.recv(self.xtors_max_count*self._xtor_id_size)
                response_data = array.array('I')
                response_data.frombytes(response_bytes)
                #print("Scanned xTors:")
                #print(' '.join([f'0x{value:08X}' for value in response_data]))
            else:
                response_data = [i for i in range(self.xtors_max_count + 1)] # dummy xTors
                self.logger.debug('Responding with dummy xTors (mmi64=False): %s' %
                ' '.join([f'0x{value:08X}' for value in response_data]))
            t3 = self.get_time_us()
        elif opcode == MTVE_GLOBALS.MMI_OPCODES.STOP.value:
            self.logger.info("stopping the MMI...")
            t3 = self.get_time_us()

        #self.print_performance_stat(opcode, t1, t2, t3)    
        self.msg_count += 1
        return(response_data)
                
    def close(self):
        # Close the socket connection
        if self._mmi64:
            self.client_socket.close()
            if self.SOCKET_TYPE == socket.AF_UNIX:
                os.unlink(self.SOCKET_PATH)
                self.logger.info('Removing socket file: %s' % self.SOCKET_PATH)

    def get_time_us(self):
        return time.time() * 1_000_000 # us

    def print_performance_stat(self, cmd_type, t1, t2, t3):
        #t1 msg_sent called
        #t2 command sent over socket
        #t3 response from C (end of transaction)
        if self.msg_count == 1:
            self.t1 = t1
            self.abs_start = t1
            self.logger.debug("\n_perf        IDX  : CALL : WRITE: RESP : TOTAL:    ABS")
        if cmd_type == MTVE_GLOBALS.MMI_OPCODES.REGIF_WRITE.value:
            ptype = 'write_perf'
        else:
            ptype = ' read_perf'
        #self.logger.debug ("%s[%6d]:%6d:%6d:%6d:%6d:%8d" % (ptype, self.msg_count, t1-self.t1, t2-t1, t3-t2, t3-t1, t3-self.abs_start))
        print ("%s[%6d]:%6d:%6d:%6d:%6d:%8d" % (ptype, self.msg_count, t1-self.t1, t2-t1, t3-t2, t3-t1, t3-self.abs_start))
        self.t1 = t3


    def queue_myself(id, queue_fname):
        with open(queue_fname, 'a') as f:
            f.write(id + '\n')
