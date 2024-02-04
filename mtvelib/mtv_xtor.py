import logging
import os
import sys

sys.path.append(os.environ.get("COMMON_UTIL") + "/sys_pkgs")
import simpy
from utils.mtvelib.mtv_imports import *

class mtv_xtor(object):
    def __init__(self, mtv, xtor_id, name):
        self.mtv = mtv
        self.xtor_id = xtor_id
        self.name = name
        self.IRQ  = mtv.IRQ
        self.UPSTREAM_FIFO = simpy.Store(mtv.env, capacity=simpy.core.Infinity)
        self.upstream_som = True
        self.upstream_mlen = 0
        self.upstream_message = None
        self.from_test = simpy.Store(mtv.env, capacity=simpy.core.Infinity)
        self.resp      = simpy.Store(mtv.env, capacity=simpy.core.Infinity) #test response
        self.from_gw   = simpy.Store(mtv.env, capacity=simpy.core.Infinity)
        self.to_gw     = simpy.Store(mtv.env, capacity=simpy.core.Infinity)
        mtv.gw_in_pipes.append(self.to_gw)
        mtv.gw_out_pipes.append(self.from_gw)

        self.cmd_fifo_credits = 0 #MTV_CMD_FIFO_DEPTH
        
        #Events:
        self.wait_all_of = []
        self.wait_any_of = []
        self.event_queue = []

        #Start self player
        mtv.env.process(self._play())

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        self.logger.info('MTVe %s xtor instantiated with id: 0x%X' % (name, xtor_id))

        self.STAT = {
            'UpstreamShortMessages' : 0,
            'UpstreamLongMessages'  : 0,
            'UpstreamEmptyMessages' : 0,
            'RegifReads'            : 0,
            'RegifWrites'           : 0,
            'Operations'            : 0,
        }

    def _play(self):
        while True:
            #Simple loop:
            # 1. Read single Burst from Upstream FIFO if IRQ is set
            # 2. Process single test command if present

            #Handle IRQ:
            if self.IRQisSet(): # priority to Upstream
                self.logger.debug('%s: Upstream FIFO is not empty' % (self.name))
                yield self.mtv.env.process(self.ReadUpstreamFIFO())
            #Handle Downstream messages:
            elif not self.waiting_4events() and len(self.from_test.items) > 0:
                msg = yield self.from_test.get()
                self.logger.debug('%s: got cmd from test: %s' % (self.name, msg))
                function = getattr(self, msg['cmd'])
                yield self.mtv.env.process(function(msg))
            else:
                #nothing todo
                if self.wait_any_of or self.wait_all_of:
                    self.logger.debug('%s: Waiting for event all_of=%s any_of=%s' %
                                      (self.name, self.wait_all_of, self.wait_any_of))
                yield self.mtv.env.timeout(1)

    def IRQisSet(self):
        return(self.IRQ[self.xtor_id])

    def ResetIRQ(self):
        self.IRQ[self.xtor_id] = False
            
    def SetIRQ(self):
        self.IRQ[self.xtor_id] = True
            
    def RegifWrite(self, msg):
        write_done = False
        enable_fc = not bool(os.environ.get("MTVE_DISABLE_FC", False))
        while not write_done:
            if not enable_fc or self.cmd_fifo_credits >= msg['burst']:
                self.cmd_fifo_credits -= msg['burst']
                self.logger.debug('%s: %s credits=%d' % (self.name, msg, self.cmd_fifo_credits))
                msg['cmd_type'] = MTVE_GLOBALS.MMI_OPCODES.REGIF_WRITE
                msg['xtor']     = self.xtor_id
                self.to_gw.put(msg)
                rsp = yield self.from_gw.get()
                self.logger.debug('%s done from GW %s' % (self.name, rsp))
                self.STAT['RegifWrites'] += 1
                write_done = True
            else:                   # command FIFO space is not sufficient for this write
                self.logger.debug('%s Not enough credits for write [%d > %d]. Updating...'
                                  % (self.name, msg['burst'], self.cmd_fifo_credits))
                self.to_gw.put(mmi_msg({
                    'cmd'      : 'ReadCMD_FIFOCredits',
                    'cmd_type' : MTVE_GLOBALS.MMI_OPCODES.REGIF_READ,
                    'xtor'     : self.xtor_id,
                    'addr'     : format_mmi_dn_address(seq=True, read=True, addr=0x1),
                    'burst'    : 1,
                }))
                fc_credits = yield self.from_gw.get()
                self.cmd_fifo_credits = fc_credits['data'] #& MTV_CMD_FIFO_DEPTH_MASK
                self.logger.debug('%s Got credit level: %d' % (self.name, self.cmd_fifo_credits))
            

    def RegifRead(self, msg):
        self.logger.debug('%s: %s' % (self.name, msg))
        msg['cmd_type'] = MTVE_GLOBALS.MMI_OPCODES.REGIF_READ
        msg['xtor']     = self.xtor_id
        self.to_gw.put(msg)
        rsp = yield self.from_gw.get()
        self.logger.debug('%s response: %s' % (self.name, rsp))
        self.resp.put(rsp)
        self.STAT['RegifReads'] += 1

    def MMIRead(self, msg):
        self.logger.debug('%s: %s' % (self.name, msg))
        msg['cmd_type'] = MTVE_GLOBALS.MMI_OPCODES.READ
        msg['xtor']     = self.xtor_id
        self.to_gw.put(msg)
        rsp = yield self.from_gw.get()
        self.logger.debug('%s response: %s' % (self.name, rsp))
        self.resp.put(rsp)
        self.STAT['Operations'] += 1

    def MMIWrite(self, msg):
        self.logger.debug('%s: %s' % (self.name, msg))
        msg['cmd_type'] = MTVE_GLOBALS.MMI_OPCODES.WRITE
        msg['xtor']     = self.xtor_id
        self.to_gw.put(msg)
        yield self.from_gw.get()
        self.logger.debug('%s done from GW' % self.name)
        self.STAT['Operations'] += 1

    def ReadUpstreamFIFO(self, length=4):
        # Read from Upstream FIFO and re-arrange the messages by header.length
        # TBD: read policy
        empty_messages = 0
        self.logger.debug('%s starting' % (self.name))
        self.to_gw.put(mmi_msg({
            'cmd'      : 'ReadUpstreamFIFO',
            'cmd_type' : MTVE_GLOBALS.MMI_OPCODES.REGIF_READ,
            'xtor'     : self.xtor_id,
            'addr'     : format_mmi_dn_address(seq=True, read=True, addr=0x0),
            'burst'    : MTV_UPSTREAM_READ_SIZE,
        }))
        rsp = yield self.from_gw.get()
        for qword in rsp:
            if self.upstream_som: # start of message
                msg = mmi_parse_response_header(qword)
                if not msg['IRQ']:
                    self.ResetIRQ()
                if msg['short']:
                    if msg['resp_type'] == UPSTREAM_RESPONSE_TYPES.EMPTY_MESSAGE.value:
                        self.logger.debug('[%s] rx empty message filtered: %s' % (self.name, msg))
                        self.STAT['UpstreamEmptyMessages'] += 1
                        empty_messages += 1
                    else:
                        self.UPSTREAM_FIFO.put(msg)
                        self.logger.debug('[%s] rx short message: %s' % (self.name, msg))
                        self.STAT['UpstreamShortMessages'] += 1
                else:
                    self.logger.debug('[%s] rx start of long message: %s' % (self.name, msg))
                    self.upstream_message = msg
                    self.upstream_som     = False
                    self.upstream_mlen    = msg['mlength']
                    self.mtv.update_irqv(msg['IRQV'])
            else:
                if not msg['IRQ']:
                    self.ResetIRQ()
                self.upstream_message['data'].append(qword)
                self.upstream_mlen -= 1
                self.logger.debug('[%s] rx long message append data: %s' % (self.name, self.upstream_message))
                if self.upstream_mlen == 0:
                    self.UPSTREAM_FIFO.put(self.upstream_message)
                    self.upstream_som = True
                    self.logger.debug('[%s] rx long message completed: %s' % (self.name, self.upstream_message))
                    self.STAT['UpstreamLongMessages'] += 1
        if empty_messages == MTV_UPSTREAM_READ_SIZE:
            self.logger.critical("[%s] The entire UpstreamFIFO is empty!!! False IRQ!" % (self.name))
        
    def waiting_4events(self):
        while len(self.event_queue) > 0:
            event = self.event_queue.pop(0)
            handled = False
            if event in self.wait_all_of:
                handled = True
                self.wait_all_of.remove(event)
                self.logger.debug("[%s] all_of=%s reduced by: {%s}"
                                  % (self.name, self.wait_all_of, event))
            if event in self.wait_any_of:
                handled = True
                self.logger.debug("[%s] any_of=%s cleared by: {%s}"
                                  % (self.name, self.wait_any_of, event))
                self.wait_any_of = []
            if not handled:
                self.logger.warning("[%s] Ignoring not-subscribed event: {%s}"
                                    % (self.name, event))
        return(self.wait_any_of or self.wait_all_of)

    def Trigger(self, event=None, target='all'):
        self.logger.debug("[%s] Sending trigger %s to %s" % (self.name, event, target))
        self.mtv.event_dispatcher(event=event, target=target, source=self.name)

    def WaitAllOf(self, event_list=[]):
        if len(self.wait_all_of) > 1:
            self.logger.warn('all_of already set. Appending. [%s] + {%s}', self.wait_all_of, event_list)
        self.wait_all_of.extend(event_list)

    def WaitAnyOf(self, event_list=[]):
        if len(self.wait_any_of) > 1:
            self.logger.warn('any_of already set. Appending. [%s] + {%s}', self.wait_any_of, event_list)
        self.wait_any_of.extend(event_list)

    def print_stat(self):
        self.logger.info("Statistics for [%s] xTOR: %s" % (self.name, self.STAT))
    
