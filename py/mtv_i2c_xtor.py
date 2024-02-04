import logging
from mtv.py.mtv_xtor    import *
from mtv.py.mtv_imports import *

class I2C_OPCODE(Enum):
    SEND_PACKET           = 0x22

class I2C_RESP_TYPE(Enum):
    RD_DONE   = 0x8
    WR_DONE   = 0x9
    TR_FAILED = 0x10
    ERR_RDWR  = 0x11
    INTERRUPT = 0x12
    I2C_INT   = 0x13

 
class I2C(mtv_xtor):

    def __init__(self, mtv, xtor_id=None, name=None):
        super().__init__(mtv, xtor_id, name)
        self.mtv = mtv
        self.xtor_id = xtor_id
        self.name = name
        self.RESP_TYPE = I2C_RESP_TYPE
        
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
            'cmd'      : 'RegifRead',
            'addr'     : format_mmi_dn_address(addr=addr,read=True),
            'burst'    : burst
        }))


    def WrImm(self, addr=0, data=[], burst=1):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=XTOR_OPCODE.CONFIG_WRITE, addr=addr, immediate=True),
            'burst'    : burst,                 
            'data'     : data
        }))
   

    def RdImm(self, addr=0, burst=1):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifRead',
            'addr'     : format_mmi_dn_address(addr=addr, read=True),
            'burst'    : burst
        }))


    def SendPacket(self, data=[0], cmd_set=0,
                   data_base=0, slave_addr=0, slave_reg_offset=0,
                   tx_payload_size=0, tot_bytes=0, write=1, rs1_st0=1, no_reg_offset_byte=0, no_size_byte=0, start=1,
                   ph_timer_expiration_val_cfg=0, ph_timer_en=0, ph_timer_strobe_cfg=0):

        cmd_reg0, cmd_reg1 = self.format_command(data_base=data_base, slave_addr=slave_addr, slave_reg_offset=slave_reg_offset,
                                                 tx_payload_size=tx_payload_size, tot_bytes=tot_bytes, write=write,
                                                 rs1_st0=rs1_st0, no_reg_offset_byte=no_reg_offset_byte,
                                                 no_size_byte=no_size_byte, start=start,
                                                 ph_timer_expiration_val_cfg=ph_timer_expiration_val_cfg,
                                                 ph_timer_en=ph_timer_en, ph_timer_strobe_cfg=ph_timer_strobe_cfg)

        self.ConfigWrite(addr=0xA, data=data)

        if cmd_set == 0:
            addr = 0
        else:
            addr = 2

        self.ConfigWrite(addr=0x0, data=[cmd_reg0, cmd_reg1], burst=2)
        #self.ConfigWrite(addr=0x0, data=[cmd_reg0])
        #self.ConfigWrite(addr=0x1, data=[cmd_reg1])

    def ReceivePacket(self, cmd_set=0,
                      data_base=0, slave_addr=0, slave_reg_offset=0,
                      tx_payload_size=0, tot_bytes=0, write=0, rs1_st0=0, no_reg_offset_byte=1,
                      no_size_byte=1, start=1,
                      ph_timer_expiration_val_cfg=0, ph_timer_en=0, ph_timer_strobe_cfg=0):

        cmd_reg0, cmd_reg1 = self.format_command(data_base=data_base, slave_addr=slave_addr,
                                                 slave_reg_offset=slave_reg_offset,
                                                 tx_payload_size=tx_payload_size, tot_bytes=tot_bytes, write=write,
                                                 rs1_st0=rs1_st0, no_reg_offset_byte=no_reg_offset_byte,
                                                 no_size_byte=no_size_byte, start=start,
                                                 ph_timer_expiration_val_cfg=ph_timer_expiration_val_cfg,
                                                 ph_timer_en=ph_timer_en, ph_timer_strobe_cfg=ph_timer_strobe_cfg)

        if cmd_set == 0:
            addr = 0
        else:
            addr = 2

        self.ConfigWrite(addr=0x0, data=[cmd_reg0, cmd_reg1], burst=2)
        #self.ConfigWrite(addr=0x0, data=[cmd_reg0])
        #self.ConfigWrite(addr=0x1, data=[cmd_reg1])
        

    def format_command(self, data_base=0, slave_addr=0, slave_reg_offset=0,
                       tx_payload_size=0, tot_bytes=0, write=1, rs1_st0=1, no_reg_offset_byte=0, no_size_byte=0, start=1,
                       ph_timer_expiration_val_cfg=0, ph_timer_en=0, ph_timer_strobe_cfg=0):
        
        cmd_reg0 = data_base & 0xFFFF
        cmd_reg0 = cmd_reg0 | ((slave_addr       & 0xFF) << 16)
        cmd_reg0 = cmd_reg0 | ((slave_reg_offset & 0xFF) << 24)
        
        cmd_reg1 =             tx_payload_size              & 0xFF
        cmd_reg1 = cmd_reg1 | ((tot_bytes                   & 0xFF) <<  8)
        cmd_reg1 = cmd_reg1 | ((write                       & 0x1)  << 16)
        cmd_reg1 = cmd_reg1 | ((rs1_st0                     & 0x1)  << 17)
        cmd_reg1 = cmd_reg1 | ((no_reg_offset_byte          & 0x1)  << 18)
        cmd_reg1 = cmd_reg1 | ((no_size_byte                & 0x1)  << 19)
        cmd_reg1 = cmd_reg1 | ((start                       & 0x1)  << 20)
        cmd_reg1 = cmd_reg1 | ((ph_timer_expiration_val_cfg & 0xFF) << 21)
        cmd_reg1 = cmd_reg1 | ((ph_timer_en                 & 0x1)  << 29)
        cmd_reg1 = cmd_reg1 | ((ph_timer_strobe_cfg         & 0x3)  << 30)

        return cmd_reg0, cmd_reg1
