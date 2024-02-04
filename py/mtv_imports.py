import sys
import os
import logging
from enum import Enum, auto

mtv_lib   = os.getenv('MTV_LIB', "")
crun_envdir = os.getenv('CRUN_ENVDIR', "")
sys.path.append(mtv_lib + "/" + crun_envdir)

from mtve_headers import *

from mtv.py.fuses.fuse    import *
from mtv.py.regs.regs     import *

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

# MTV_RTC_PERIOD_IN_NS        = 10
# MTV_MAX_XTORS               = 32
# MTV_IRQ_ADDR                = 0
# MTV_RTC_ADDR                = 1
# MTV_CMD_FIFO_DEPTH          = 16
# MTV_CMD_FIFO_DEPTH_MASK     = 0xFFFFFF

MTV_UPSTREAM_READ_SIZE      = 0x4

class XTOR_OPCODE(Enum):
    CONFIG_WRITE                =  0
    CONFIG_READ                 =  1
    SEQ_LOOPBACK_NOTIFICATION   =  2
    WAIT_SYSTEM_TIME            =  8
    WAIT_RELATIVE_TIME          =  9
    TRIGGER_EVENT               = 10
    WAIT_ANY_EVENT              = 11
    WAIT_ALL_EVENT              = 12

class UPSTREAM_RESPONSE_TYPES(Enum):
    EMPTY_MESSAGE	        = 0
    CONFIG_READ                 = 1
    SEQ_LOOPBACK_NOTIFICATION	= 2
    XTOR_SPECIFIC_TYPE          = auto()

    @classmethod
    def _missing_(cls, value):
        for member in cls:
            if member.value == value:
                return member
        return cls.XTOR_SPECIFIC_TYPE


XTOR_MAP = MTVE_GLOBALS.XTOR_MAP


class SW_HW_XTOR_MAP(Enum):
    EC   = 'I2C_1'
    PD   = 'I2C_2'
    TCPC = 'I2C_3'
    GOTIC = 'DUT'

class GPIO_MAP(Enum):
    RESET_N    = 0
    RESERVED_1 = 1
    RESERVED_2 = 2
    RESERVED_3 = 3
    RESERVED_4 = 4
    RESERVED_5 = 5
    
class mmi_msg(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __str__(self):
        d = self.copy()
        data = d.get('data', [])
        if data:
            d['data'] = ['0x' + format(value,'X') for value in data]
        for key, value in d.items():
            if isinstance(value, int):
               d[key] = '0x' + format(value,'X')
        return repr(d)


class mmi_upstream_msg(dict):
    def __init__(self, rsp):
        super().__init__(rsp)

    def __str__(self):
        d = self.copy()
        data = d.get('data', [])
        if data:
            if d.get('short', True):
                d['data'] = hex(data)
            else:
                d['data'] = ['0x' + format(int(value),'X') for value in data]
        resp_type =  d.get('resp_type', None)
        #logger.debug("RESP_TYPE: %s, %s" % (resp_type, UPSTREAM_RESPONSE_TYPES(int(resp_type))))
        if UPSTREAM_RESPONSE_TYPES(resp_type) == UPSTREAM_RESPONSE_TYPES.XTOR_SPECIFIC_TYPE:
            d['resp_type'] = 'XTOR_SPECIFIC_TYPE='+str(resp_type)
        else:
            d['resp_type'] = UPSTREAM_RESPONSE_TYPES(resp_type)
        return repr(d)

class mmi_data_rsp(dict):
    def __init__(self, rsp):
        super().__init__(rsp)

    def __str__(self):
        d = self.copy()
        data = d.get('data', [])
        if data:
            d['data'] = [f'0x{data:08X}']
        return repr(d)
    
def format_mmi_dn_address(short=True, seq=False, opcode=0, addr=0,
                          read=False, immediate=False):
    address = 0x0 # 16 bit
    SEQ_LSB  = 15
    ADDR_LSB =  0
    if seq:
        address = address | 1 << SEQ_LSB
    if not read:
        IM_LSB   = 14
        CMD_LSB  =  8
        if immediate:
            address = address | 1 << IM_LSB
        address = address | (opcode.value << CMD_LSB)
    address = address | (addr << ADDR_LSB)
    return address


def mmi_cfg_read_response(data):
    rsp = mmi_data_rsp({
        'data' : data
    })
    return rsp

def mmi_parse_response_header(header):
    SEQ_LSB      = 63
    SHORT_LSB    = 62
    IRQ_LSB      = 61
    RSP_TYPE_MSB = 60
    RSP_TYPE_LSB = 40
    BSIZE_MSB    = 39    
    BSIZE_LSB    = 32    
    DATA_MSB     = 31
    DATA_LSB     =  0

    seq       = bool(header    >> SEQ_LSB      & 0x1)
    short     = bool(header    >> SHORT_LSB    & 0x1)
    IRQ       = bool(header    >> IRQ_LSB      & 0x1)
    resp_type = header         >> RSP_TYPE_LSB & ((1 << (RSP_TYPE_MSB-RSP_TYPE_LSB+1)) - 1)
    mlen_rsv  = header         >> BSIZE_LSB    & ((1 << (BSIZE_MSB-BSIZE_LSB+1))       - 1)
    irqv_data = header         >> DATA_LSB     & ((1 << (DATA_MSB-DATA_LSB+1))         - 1)

    rsp = mmi_upstream_msg({ 
        'seq'       : seq,
        'short'     : short,
        'IRQ'       : IRQ,
        'resp_type' : resp_type,
        'data'      : []
    })

    if short:
        rsp['reserved'] = mlen_rsv
        rsp['data']     = irqv_data
    else:
        rsp['mlength']    = mlen_rsv
        rsp['IRQV']       = format(irqv_data, f'032b')
          
    return rsp


"""
class one2many(object):
    def __init__(self, env, capacity=simpy.core.Infinity):
        self.env = env
        self.capacity = capacity
        self.pipes = []

    def put(self, value):
        if not self.pipes:
            raise RuntimeError('There are no output pipes.')
        events = [store.put(value) for store in self.pipes]
        return self.env.all_of(events)  # Condition event for all "events"

    def set_output_conn(self, pipe):
        self.pipes.append(pipe)
        return pipe
    
class many2one(object):
    def __init__(self, env, capacity=simpy.core.Infinity):
        self.env = env
        self.capacity = capacity
        self.pipes = []
        
    def set_input_conn(self, pipe):
        #pipe = simpy.Store(self.env, capacity=self.capacity)
        self.pipes.append(pipe)
        return pipe

    def get(self):
        if not self.pipes:
            raise RuntimeError('There are no input pipes.')
        event_list = []
        for pipe in self.pipes:
            while len(pipe.items) > 0:
                event_list.append(pipe.get)
        return event_list
"""
