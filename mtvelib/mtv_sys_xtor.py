import logging
from utils.mtvelib.mtv_xtor    import *
from utils.mtvelib.mtv_imports import *

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class SYS(mtv_xtor):

    def __init__(self, mtv, xtor_id=None, name=None):
        super().__init__(mtv, xtor_id, name)
        self.mtv = mtv
        self.xtor_id = xtor_id
        self.name = name
        self.RTC = 0

    def ConfigWrite(self, addr=0, data=[], burst=1):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=XTOR_OPCODE.CONFIG_WRITE,
                                               addr=addr),
            'burst'    : burst,                 
            'data'     : data
        }))
   

    def ConfigRead(self, addr=0, burst=1):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(addr=addr, opcode=XTOR_OPCODE.CONFIG_READ),
            'burst'    : burst
        }))


    def WrImm(self, addr=0, data=[], burst=1):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=XTOR_OPCODE.CONFIG_WRITE, addr=addr,
                                               immediate=True),
            'burst'    : burst,                 
            'data'     : data
        }))
   

    def RdImm(self, addr=0, burst=1):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifRead',
            'addr'     : format_mmi_dn_address(addr=addr, read=True),
            'burst'    : burst
        }))


    def fetch_irq(self, with_rtc=False):
        burst_size = 1
        if with_rtc:
            burst_size = 2
        msg = mmi_msg({
            'xtor'     : self.xtor_id,
            'cmd'      : 'FetchIRQ',
            'cmd_type' : MTVE_GLOBALS.MMI_OPCODES.REGIF_READ,
            'addr'     : format_mmi_dn_address(seq=False, read = True, addr=MTVE_GLOBALS.MTV_IRQ_ADDR),
            'burst'    : burst_size
        })
        
        rsp = self.mtv.send_mmi_msg(msg)
        if with_rtc:
            irq = rsp[0]['data']
            self.RTC = rsp[1]['data']
            logger.debug("RTC = %f us at simulation cycle %d" %
                         (self.RTC*MTVE_GLOBALS.MTV_RTC_PERIOD_IN_NS/1000, self.mtv.env.now))
        else:
            irq = rsp['data']
            
        irq = irq & 0xFFFFFFFF
        return format(irq, f'032b')

    
    def fetch_rtc(self):
        msg = mmi_msg({
            'xtor'     : self.xtor_id,
            'cmd'      : 'FetchRTC',
            'cmd_type' : MTVE_GLOBALS.MMI_OPCODES.REGIF_READ,
            'addr'     : format_mmi_dn_address(seq=False, read = True, addr=MTVE_GLOBALS.MTV_RTC_ADDR),
            'burst'    : 1
        })

        self.RTC = self.mtv.send_mmi_msg(msg)['data']
        
