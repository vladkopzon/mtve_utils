import logging
import simpy
from mtv.py.mtv_xtor    import *
from mtv.py.mtv_imports import *

###################################################################################
###
### JTAG XTOR
###
###################################################################################

class JTAG_OPCODE(Enum):
    JTAG_READ_CMD  = 0x22
    JTAG_WRITE_CMD = 0x23
    READ_CFG_SPACE = 0x24

class JTAG(mtv_xtor):


    ## Sequencer commands 
    XTOR_WR_CMD = 0x9600
    XTOR_RD_CMD = 0x9500

    ## XTOR config addresses
    MTVE_JTAG_JTAG_INFO_ADDR   = 0
    MTVE_JTAG_JTAG_CLK_ADDR    = 1
    MTVE_JTAG_JTAG_CMD_ADDR    = 2
    MTVE_JTAG_SHIFT_CNT_ADDR   = 3
    MTVE_JTAG_TMS_VECTOR_ADDR  = 4
    MTVE_JTAG_TDI_VECTOR_ADDR  = 5
    MTVE_JTAG_START_CMD_ADDR   = 6
    MTVE_JTAG_DATA_ADDR        = 7
    MTVE_JTAG_CMD_DONE_ADDR    = 8
    MTVE_JTAG_REG_SIZE         = 9
    
    ## JTAG CMD types
    JTAG_REG   =  0
    JTAG_MTAP  =  1
    JTAG_DATA  =  2

    DEVICE_REVICE_MODE = 0
    MTAP_IDCODE = 2
    
    ##
    JTAG_CMD_SIZE   = 32
        
    ## IR Commands
    CTRL_PORT_CMD   = 0x38
    CTRL_PORT_DATA  = 0x39
    CTRL_PORT_READ  = 0x3A
    CTRL_PORT_WRITE = 0x3B
        
    MTAP_NETWORK          = 0x12
    TAPNW_NUMBER_OF_STAPS = 0x7

    ## XTOR Commands
    JTAG_START_WR_CMD = 1
    JTAG_START_RD_CMD = 3

    ##
    JTAG_CMD_BURST_SIZE = 5

    
    def __init__(self, mtv, xtor_id=None, name=None):
        super().__init__(mtv, xtor_id, name)
        self.mtv = mtv
        self.xtor_id = xtor_id
        self.name = name
        

    ###################################################
    # Reset
    ###################################################
    def Reset(self):

        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : self.XTOR_WR_CMD,
            'burst'    : 1,                 
            'data'     : [0x0000000000000001]
        }))
        

    ###################################################
    # GetJTAGStatus
    ###################################################
    def GetJTAGStatus(self):
        self.from_test.put(mmi_msg({
            #'cmd'      : 'RegifWrite',
            'cmd'      : 'RegifRead',
            #'addr'     : self.XTOR_RD_CMD,
            'addr'     : format_mmi_dn_address(addr=0, opcode=JTAG_OPCODE.READ_CFG_SPACE),
            'burst'    : self.MTVE_JTAG_REG_SIZE,                 
        }))

    
    ###################################################
    # jtag_wr_config_reg 
    ###################################################
    def jtag_wr_config_reg(self,addr,data):

        print("jtag_wr_reg addr:",addr," data:",data)
        
        reg_addr = self.XTOR_WR_CMD + addr
        
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : reg_addr,
            'burst'    : 1,                 
            'data'     : [data]
        }))

        return 1

    ###################################################
    # jtag_rd_reg
    ###################################################
    def jtag_rd_config_reg(self,addr):

        print("jtag_rd_config_reg addr:",addr)

        reg_addr = self.XTOR_RD_CMD + addr

        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifRead',
            'addr'     : format_mmi_dn_address(addr=addr, read=True),
            'burst'    : 1           
        }))
        
        return 1

    ###################################################
    # jtag_gen_cmd
    ###################################################
    def jtag_gen_cmd (self,jtag_cmd,tms,tdi,shift_cnt,read: bool):

        print("jtag_gen_cmd jtag_cmd: ",jtag_cmd," tms: ",tms," tdi: ",tdi," shift_cnt: ",shift_cnt)
        
        # Set JTAG params in config space
        # change to single burst

        if (read):
            START_CMD = self.JTAG_START_RD_CMD
        else:
            START_CMD = self.JTAG_START_WR_CMD
            
        wr_data = [jtag_cmd,
                   shift_cnt,
                   tms      ,
                   tdi      ,
                   START_CMD];

        #reg_addr = self.XTOR_WR_CMD + self.MTVE_JTAG_JTAG_CMD_ADDR
        reg_addr = self.MTVE_JTAG_JTAG_CMD_ADDR
        
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            #'addr'     : reg_addr,
            'addr'     : format_mmi_dn_address(addr=reg_addr, opcode=XTOR_OPCODE.CONFIG_WRITE),
            'burst'    : self.JTAG_CMD_BURST_SIZE,                 
            'data'     : wr_data
        }))
        
        return 1

    ###################################################
    # jtag_command_8b
    ###################################################
    def jtag_command_8b (self,opcode):

        print("jtag_command_8b opcode: ",opcode)
        
        tms_vector = 0x80
        tdi_vector = opcode
        
        shift_cnt  = 8
        
        self.jtag_gen_cmd(self.JTAG_REG,tms_vector,tdi_vector,shift_cnt,read=False)
        
        return 1


    ###################################################
    # prd_test_ee_mtap_option
    ###################################################
    def prd_test_ee_mtap_option(self,sel_opt):

        print("Calling prd_test_ee_mtap_option with sel_opt = ",sel_opt)
        
        self.jtag_command_8b(self.MTAP_NETWORK)
        
        if sel_opt == 4:
            cltapc_select = 0x0001
        elif sel_opt == 5:
            cltapc_select = 0x0004
        elif sel_opt == 6:
            cltapc_select = 0x0010
        elif sel_opt == 7:
            cltapc_select = 0x0040
        elif sel_opt == 8:
            cltapc_select = 0x0100
        elif sel_opt == 9:
            cltapc_select = 0x0400
        elif sel_opt == 10:
            cltapc_select = 0x1000
        else:
            cltapc_select = 0x0000
            
        self.jtag_data_mtap(cltapc_select,(self.TAPNW_NUMBER_OF_STAPS * 2))
            
        return 1


    ###################################################
    # jtag_data_mtap
    ###################################################
    def jtag_data_mtap(self,data_in,shift_cnt):
    
        print("Calling jtag_data_mtap with data_in: ",data_in," shift_cnt: ",shift_cnt)
        
        tms_vector = 0;
        tdi_vector = 0;
        
        tms_vector = 1 << (shift_cnt-1)
        tdi_vector = data_in
                  
        self.jtag_gen_cmd(self.JTAG_MTAP,tms_vector,tdi_vector,shift_cnt,read=False)
   
        return 1


    ###################################################
    # jtag_inv_data32
    ###################################################
    def jtag_inv_data32(self,data_in,shift_cnt,read):

        print("jtag_inv_data32 data_in:",data_in)

        tms_vector = 0
        tdi_vector = 0
        
        for _ in range(32):
            tdi_vector = (tdi_vector << 1) | (data_in & 1)
            data_in >>= 1
            
        self.jtag_gen_cmd(self.JTAG_DATA,tms_vector,tdi_vector,shift_cnt,read)
            
        return 1

    ###################################################
    # jtag_command
    ###################################################
    def jtag_command(self,opcode):

        print("jtag_command opcode:",opcode)
        
        tms_vector = 0x2000
    
        tdi_vector = opcode | 0x3fc0

        self.jtag_gen_cmd(self.JTAG_REG,tms_vector,tdi_vector,14,read=False);
  
        return 1


    ###################################################
    # jtag_command
    ###################################################
    def jtag_write_ctrl_port_macro(self,address,data_in):

        print("jtag_write_ctrl_port_macro address:",address," data_in:",data_in)
      
        self.jtag_command(self.CTRL_PORT_DATA)
        
        self.jtag_inv_data32(data_in,self.JTAG_CMD_SIZE,read=False)
        
        self.jtag_command(self.CTRL_PORT_CMD)
        
        tmp_data = address | ( 1 << 21) # {7'h00, 4'b0001, address[20:0]
        
        self.jtag_inv_data32(tmp_data,self.JTAG_CMD_SIZE,read=False)
        
        return 1

    ###################################################
    # jtag_read_ctrl_port_macro
    ###################################################
    def jtag_read_ctrl_port_macro(self,address):

        print("jtag_read_ctrl_port_macro address:",address)
      
        self.jtag_command(self.CTRL_PORT_CMD)
        
        tmp_data = address | ( 0 << 21) # {7'h00, 4'b0000, address[20:0]
        
        self.jtag_inv_data32(tmp_data,self.JTAG_CMD_SIZE,read=False)
        
        self.jtag_command(self.CTRL_PORT_READ)
        
        self.jtag_inv_data32(0,self.JTAG_CMD_SIZE,read=True)
        
        return 1

    ###################################################
    # jtag_tar_read
    ###################################################
    def jtag_tar_read(self, tar_cs, tar_port, tar_index):
        
        reg_addr = ( tar_cs << 19 ) | ( tar_port << 13) | tar_index
        
        rd_data = self.jtag_read_ctrl_port_macro(reg_addr)

        return rd_data
            
        
    ###################################################
    # jtag_tar_write
    ###################################################
    def jtag_tar_write(self, tar_cs, tar_port, tar_index, tar_wr_data):
        
        reg_addr = ( tar_cs << 19 ) | ( tar_port << 13) | tar_index
        
        self.jtag_write_ctrl_port_macro(reg_addr, tar_wr_data)

        return 1

    
    ###################################################
    # Read MTAP ID
    ###################################################
    def jtag_read_mtap_id(self):

        print("jtag_read_mtap_id")
      
        self.prd_test_ee_mtap_option(self.DEVICE_REVICE_MODE)
        
        self.jtag_command_8b(self.MTAP_IDCODE)

        tmp_data = 0
        self.jtag_inv_data32(tmp_data,self.JTAG_CMD_SIZE,read=True)
        
        return 1
    
