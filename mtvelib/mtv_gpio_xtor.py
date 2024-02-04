import logging
import simpy
from utils.mtvelib.mtv_xtor    import *
from utils.mtvelib.mtv_imports import *

class GPIO_OPCODE(Enum):
    SET_H_GPIO            = 0x32
    SET_L_GPIO            = 0x33
    TOGGLE_GPIO           = 0x34
    PULSE_GPIO            = 0x35
 

class GPIO(mtv_xtor):

    def __init__(self, mtv, xtor_id=None, name=None):
        super().__init__(mtv, xtor_id, name)
        self.mtv = mtv
        self.xtor_id = xtor_id
        self.name = name

    def BulkGPIOConfig(self, gpio_idx=0, config_table=[]):
        #config table: [intr_val,intr,driven_strn,slew_rate,init_val,oen]
        
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=XTOR_OPCODE.CONFIG_WRITE, addr=gpio_idx),
            'burst'    : len(config_table),                 
            'data'     : [format_gpio_cfg(*gpio) for gpio in config_table]
       }))
   
    def ConfigWr(self, GPIOn=0, intr_val=0,intr=0,driven_strn=0,slew_rate=0,init_val=0,oen=0):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=XTOR_OPCODE.CONFIG_WRITE, addr=GPIOn),
            'burst'    : 1,                 
            'data'     : [format_gpio_cfg(intr_val,intr,driven_strn,slew_rate,init_val,oen)]
        }))
   

    def ConfigRd(self, GPIOn=0):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(addr=GPIOn, opcode=XTOR_OPCODE.CONFIG_READ),
            'burst'    : 1
        }))

    def WrImm(self, GPIOn=0, intr_val=0,intr=0,driven_strn=0,slew_rate=0,init_val=0,oen=0):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=XTOR_OPCODE.CONFIG_WRITE, addr=GPIOn, immediate=True),
            'burst'    : 1,                 
            'data'     : [format_gpio_cfg(intr_val,intr,driven_strn,slew_rate,init_val,oen)]
        }))
   
    def RdImm(self, GPIOn=0):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifRead',
            'addr'     : format_mmi_dn_address(addr=GPIOn, read=True),
            'burst'    : 1
        }))
        
    def GpioVal(self, Addr=0x20):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifRead',
            'addr'     : format_mmi_dn_address(addr=Addr, read=True),
            'burst'    : 1
        }))
        
    def GpioSetHigh(self, GPIOn=0):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=GPIO_OPCODE.SET_H_GPIO,
                                               addr=0x0),
            'burst'    : 1,                 
            'data'     : [GPIOn]
        }))
        
    def GpioSetLow(self, GPIOn=0):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=GPIO_OPCODE.SET_L_GPIO,
                                               addr=0x0),
            'burst'    : 1,                 
            'data'     : [GPIOn]
        }))

    def GpioToggle(self, GPIOn=0):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=GPIO_OPCODE.TOGGLE_GPIO,
                                               addr=0x0),
            'burst'    : 1,                 
            'data'     : [GPIOn]
        }))

        
    def GpioPulse(self, GPIOn=0, PulseWidth=0):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=GPIO_OPCODE.PULSE_GPIO,
                                               addr=GPIOn),
            'burst'    : 1,                 
            'data'     : [PulseWidth]
        }))

    def MMIWr(self, GPIOn=0):
        self.from_test.put(mmi_msg({
            'cmd'      : 'MMIWrite',
            'addr'     : format_mmi_dn_address(opcode=GPIO_OPCODE.CONFIG_WRITE_GPIO,
                                               addr=GPIOn),
            'burst'    : 1
        }))


def format_gpio_cfg(intr_val=0,intr=0,driven_strn=0,slew_rate=0,init_val=0,oen=0):
    INTR_VAL_LSB       =  28
    INTR_LSB           =  24
    DRIVEN_STRN_LSB   =  16
    SLEW_RATE_LSB     =  8
    INIT_LSB          =  4
    OEN_LSB           =  0

    data = 0x0               #rdata_vld12 64 bit
    data = data | (intr_val << INTR_VAL_LSB)
    data = data | (intr << INTR_LSB)
    data = data | (driven_strn << DRIVEN_STRN_LSB)
    data = data | (slew_rate << SLEW_RATE_LSB)
    data = data | (init_val << INIT_LSB)
    data = data | (oen << OEN_LSB)
    return data
