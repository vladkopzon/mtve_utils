import logging
from mtv_dut_xtor import *
from mtv_imports  import *

class GBR(mtv_dut_xtor):

    def __init__(self, mtv, xtor_id=None, name=None):
        super().__init__(mtv, xtor_id, name)
        self.mtv = mtv
        self.xtor_id = xtor_id
        self.name = name

    def ConfigWrite(self, addr=0, data=[], burst=1):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=XTOR_OPCODE.CONFIG_WRITE, addr=addr),
            'burst'    : burst,                 
            'data'     : data
        }))
   

