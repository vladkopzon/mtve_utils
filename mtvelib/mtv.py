import logging
import os
import sys
import re
import bisect

sys.path.append(os.environ.get("COMMON_UTIL") + "/sys_pkgs")
import simpy

from mtv.py.mtv_imports   import *
from mtv.py.mmi_connector import *
from mtv.py.mtv_xtor      import *
from mtv.py.mtv_sys_xtor  import *
from mtv.py.mtv_dut_xtor  import *
from mtv.py.mtv_gpio_xtor import *
from mtv.py.mtv_jtag_xtor import *
from mtv.py.mtv_i2c_xtor  import *
from mtv.py.mtv_lsx_xtor  import *


class mtv (object):
    
    def __init__(self, mmi64=True, host='127.0.0.1', port=2300, simpy_mode=None):
        self.MAX_CYCLES_TO_RUN = 1000000
        self.MAX_IDLE_CYCLES   = 1000
        self.MAX_IDLE_AFTER_TEST_STOP = 10
        logging.basicConfig(format='%(levelname)s - %(module)s.%(funcName)s - %(message)s')
        self.log = logging.getLogger(__name__)
        self.log.setLevel(logging.DEBUG) # DEBUG
        self.mmi64 = mmi64

        port = int(os.environ.get("MTVe_Port", port))
        host = os.environ.get("MTVe_HostAddress", host) 
        self.mmi_connector = mmi_connector(host = host, mtv=self, port = port,
                                           mmi64=mmi64)
        self.env = simpy.Environment()
        self.gw_in_pipes = []
        self.gw_out_pipes = []
        self.gw = self.env.process(self.mmi_gateway())
        #global response to test (to merge with SYS?)
        self.resp = simpy.Store(self.env, capacity=simpy.core.Infinity)
        self.log.info("simpy initialized")

        #scan FPGA for all xTors:
        #self._xtors = self.mmi_connector.send_msg([MTVE_GLOBALS.MMI_OPCODES.SCAN.value])
        self._xtors = self.mmi_connector.send_msg([MTVE_GLOBALS.MMI_OPCODES.SCAN.value])
        self._unmapped_xtors = self._xtors
        self._sw_xtors = ['EC', 'PD']
        self.log.info("Scanned xTors: %s", self._xtors)
        self.initialized_xtors = []

        #IRQ vector:
        self.periodic_irq_fetch_en = True
        self.IRQ      = [False] * MTVE_GLOBALS.MTV_MAX_XTORS
        self.IRQ_MASK = [False] * MTVE_GLOBALS.MTV_MAX_XTORS

        #RTC
        self.RTC_EN = True
        self.TIMERS = []
        self.TIMERS2EVENTS = {}
        
        #install SYS xTor:
        self.SYS = self.init_hw_xtor(name='SYS', xtype='SYS') 
        self.SYS.fetch_rtc()

        #init time
        self.starttime = self.get_time_us(absolute=True)

        #
        self.stop_on_timeout = False
        
    def update_irqv(self, vector):
        for i in range(len(self.IRQ)):
            self.IRQ[i] = self.IRQ_MASK[i] & bool(int(vector[31-i])) # IRQ vector is a big-endian vector
                        
    def send_mmi_msg(self, msg):
        array_data = [          # default is IRQ read
            msg['cmd_type'].value,
            msg.get('xtor', 0),
            msg.get('addr', 0),
            msg.get('burst', 1)
        ] + msg.get('data', [])
        
        self.log.debug('Msg to mmi_connector: %s' % msg)
        rsp = self.mmi_connector.send_msg(array_data)
        rsp_list = []

        if msg['cmd_type'] == MTVE_GLOBALS.MMI_OPCODES.STOP:
            self.exit()
        else:
            # All responses will be returned as a list of message(s):
            #       1. Single ConfigRead (burst == 1)
            #       2. Burst ConfigRead (it is just an aggregated stream of data responses
            #          to multiple ConfigReads)
            #       3. ReadUpstreamFIFO (also it is just a burst ConfigRead, in opposite to
            #          ConfigRead, returned data format should be parsed in a context of read
            #          from UpstreamFIFO. It could be either short or long UpstreamMessages.
            #          Short messages can be parsd here. Long messages will be parsd by base_xtor
            #          to perform the correct re-asembly on message boundary.

            if (msg['cmd'] == 'ReadUpstreamFIFO'):
                return rsp
                # if msg['burst'] == 1:
                #     rsp_list.append(mmi_short_response(rsp[0]))
                # else:
                #     self.log.error('ReadUpstreamFIFO not allowed with burst != 1 parmeter', msg)
            elif (msg['cmd_type'] == MTVE_GLOBALS.MMI_OPCODES.REGIF_READ):
                for i in range(msg['burst']):
                    rsp_list.append(mmi_cfg_read_response(rsp[i]))

                if len(rsp_list) == 1:
                    return rsp_list[0]  # return message itself
                else:
                    return(rsp_list)
        
    def exit(self):
        self.mmi_connector.close()

    def init_hw_xtor(self, name=None, xtype=None):
        xtor_id = getattr(XTOR_MAP, xtype).value
        xtor_object_name = re.sub(r"_\d$", "", xtype)
        self.log.debug('Initiating xtor: %s, id: %s' % (xtype, xtor_id))
        if xtor_id in self._unmapped_xtors:
            self._unmapped_xtors.remove(xtor_id)
            xtor_object = globals().get(xtor_object_name)
            if xtor_object:
                # Initialize the class object
                instance = xtor_object(mtv=self, xtor_id=xtor_id, name=name)
                self.IRQ_MASK[xtor_id] = True
            else:
                raise ValueError("Class not found:", xtor_object_name)
        else:
            raise ValueError("xTor %s not available for init." % xtype)
        self.log.debug ('Unmapped xTors: %s' % self._unmapped_xtors)
        self.initialized_xtors.append(instance)
        return(instance)

    def init_sw_xtor(self, name=None, xtype=None):
        self.log.debug('Initiating sw xtor: %s' % (xtype))
        if xtype in self._sw_xtors:
            xtor_object = globals().get(xtype)
            if xtor_object:
                # Initialize the class object
                instance = xtor_object(mtv=self, xtype=xtype, name=name)
            else:
                raise ValueError("Class not found:", xtype)
        else:
            raise ValueError("xTor %s not available for init." % xtype)
            self.log.debug ('Available sw xtors: ', self._sw_xtors)
        return(instance)

    def mmi_gateway(self):
        test_completed = False
        idle_cycles    = 0
        while True:
            served = False
            i = 0
            for pipe in self.gw_in_pipes:
                #self.log.debug('Gateway pipe %d length is %d' % (i, len(pipe.items)))
                if len(pipe.items) > 0:
                    msg = yield pipe.get()
                    self.log.debug('msg to send: %s' % msg)
                    if i == 0 and msg['cmd_type'] == MTVE_GLOBALS.MMI_OPCODES.STOP:  # on control pipe
                        self.log.info('got MMI_OPCODES.STOP command. Waiting for end of playlist')
                        test_completed = True
                        stop_msg = msg
                        i +=1
                        continue
                    rsp_msg = self.send_mmi_msg(msg)
                    self.log.debug('pipe %d response is %s' % (i, rsp_msg))
                    self.gw_out_pipes[i].put(rsp_msg)
                    served = True
                    idle_cycles = 0
                i += 1

            if not served:
                self.process_timers()
                if self.periodic_irq_fetch_en and idle_cycles % 2 == 1:
                    self.log.debug('Fetching IRQ vector at cycle %d' % self.env.now)
                    irq = self.SYS.fetch_irq(with_rtc=self.RTC_EN)
                    self.update_irqv(irq)
                    #self.log.debug('IRQ vector [%s]', irq)
                if any(self.IRQ):
                    idle_cycles = 0
                    self.pretty_print_IRQ_vector()
                else:
                    idle_cycles +=1
                    self.log.debug('idle cycles = %d (%d)' % (idle_cycles, test_completed))
                    if test_completed and idle_cycles > self.MAX_IDLE_AFTER_TEST_STOP:
                        self.log.debug('msg to send: %s' % stop_msg)
                        rsp_msg = self.send_mmi_msg(stop_msg)
                        self.log.info('MTVe playback done')
                        self.resp.put(rsp_msg)
                        for xtor in self.initialized_xtors:
                            xtor.print_stat()
                        self.log.debug('MTVe closing gateway at cycle: %d' % self.env.now)
                        if self.stop_on_timeout:
                            raise simpy.Interrupt('TIMEOUT')
                        else:
                            raise simpy.Interrupt('Simulation finished')
                yield self.env.timeout(1)
            if self.env.now == self.MAX_CYCLES_TO_RUN or idle_cycles > self.MAX_IDLE_CYCLES:
                self.stop_on_timeout = True
                self.stop_test()
                self.log.info(f'Stopping gateway: CYCLES={self.env.now}, IDLE_CYCLES={idle_cycles}')

    def stop_test(self):
        self.log.info('STOP_TEST called!')
        self.gw_in_pipes[0].put({'cmd_type' : MTVE_GLOBALS.MMI_OPCODES.STOP})


    def event_dispatcher(self, event=[], target='all', source=None):
        self.log.debug('Dispatching event: %s to %s' % (event, target))
        event_dispatched = False
        for xtor in self.initialized_xtors:
            if  xtor.name == source:
                event_dispatched = True
            elif target == 'all' or target == xtor.name:
                xtor.event_queue.append(event)
                event_dispatched = True
        if not event_dispatched:
            self.log.error('Unable to dispatch event. No destination found: [%s]', target)


    def IRQ_pull_enable(self, value=True):
        self.periodic_irq_fetch_en = value


    def pretty_print_IRQ_vector(self):
        asserted_irqs = []
        if any(self.IRQ):
            #self.log.debug('IRQ is not empty.')
            for i in range(len(self.IRQ)):
                if self.IRQ[i]:
                    asserted_irqs.append(XTOR_MAP(i).name)
            self.log.debug('IRQ (after mask) is set for %s at %d'
                           % (asserted_irqs, self.get_time_us()))
        else:
            self.log.debug('IRQ is empty.')

    def get_time_us(self, absolute=False):
        t = time.time() * 1_000_000 # us
        if not absolute:
            t -= self.starttime
        return t
        

################################################################################
# Timers control:

    def set_timer(self, sec= 0, ms=0, us=0, ns=0, name='unnamed'):
        uS=1000 #ns
        mS=uS*1000
        sS=mS*1000
        resume_time = self.SYS.RTC + ns + us*uS + ms*mS + sec*sS
        timer = self.env.event()
        if not resume_time in self.TIMERS2EVENTS:
            bisect.insort(self.TIMERS, resume_time)
            self.TIMERS2EVENTS[resume_time] = []
        self.TIMERS2EVENTS[resume_time].append({'event':timer, 'name':name})
        self.log.debug('[%s] will wake at %d ns [%d timers] [total timer %d]' %
                       (name, resume_time, len (self.TIMERS2EVENTS[resume_time]),
                        len(self.TIMERS)))
        return timer
        
    def process_timers(self):
        done = False
        while not done and self.TIMERS:
            if self.SYS.RTC >= self.TIMERS[0]:
                for timer in self.TIMERS2EVENTS[self.TIMERS[0]]:
                    self.log.debug('waking timer %s set for %d at %d [ns]' %
                                   (timer, self.TIMERS[0], self.SYS.RTC))
                    timer['event'].succeed()
                self.TIMERS.pop(0)
            else:
                done = True

    def run(self, *args, **kwargs):
        try:
            self.env.run(*args, **kwargs)
        except Exception as e:
            if e.cause != 'Simulation finished':
                print(f'ERROR : Simpy: {e}')

        print('Simulation finished.')
        
