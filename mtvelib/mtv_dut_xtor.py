import logging
from utils.mtvelib.mtv_xtor    import *
from utils.mtvelib.mtv_imports import *

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


class DUT(mtv_xtor):
    #Rom LC REG Wr/Rd    
    ROM_ADDR_REG = 33
    ROM_WRDATA_REG = 34 
    ROM_RDDATA_REG = 35

    PD_XTOR_IRAM_ADDR_REG   = 41
    PD_XTOR_IRAM_WRDATA_REG = 42
    PD_XTOR_IRAM_RDDATA_REG = 43

    MTV_PD_XTOR_IRAM_START  = 64
    MTV_PD_XTOR_DRAM_START  = 128
    

    PD_XTOR_RST_REG         = 47
    
    #Fuse Regs 
    FUSE_REG0      = 12
    FUSE_REG1      = 13
    
    def __init__(self, mtv, xtor_id=None, name=None):
        super().__init__(mtv, xtor_id, name)
        self.mtv = mtv
        self.xtor_id = xtor_id
        self.name = name

    def ConfigWr(self, addr=0, data=0, burst=1):
        logger.info(f'ConfigWr {addr} {data} {burst}')   

        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifWrite',
            'addr'     : format_mmi_dn_address(opcode=XTOR_OPCODE.CONFIG_WRITE, addr=addr),
            'burst'    : burst,                 
            'data'     : data
        }))
   

    def ConfigRd(self, addr=0, burst=1):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifRead',
            'addr'     : format_mmi_dn_address(addr=addr, read=True),
            'burst'    : burst
        }))

    def BuildVer(self, addr=2, burst=1):
        self.from_test.put(mmi_msg({
            'cmd'      : 'RegifRead',
            'addr'     : format_mmi_dn_address(addr=addr, read=True),
            'burst'    : burst
        }))

    def LoadFuses(self,fuse_vector=None):
        logger.info(f'Overloading fuse vector')   
        logger.debug(f'fuse_vector {fuse_vector}')

        #MTV_DUT_FUSE_ARRAY_WR_DATA_WIDTH = 16
        #MTV_DUT_FUSE_ARRAY_WE_RANGE_MSB  = 15
        #MTV_DUT_FUSE_ARRAY_WE_DATA_LSB   = 16
        
        chunk_width = MTVE_GLOBALS.MTV_DUT_FUSE_ARRAY_WR_DATA_WIDTH
        
        chunks = [fuse_vector[i:i+chunk_width] \
                  for i in range(0, len(fuse_vector), chunk_width)]
        mmi_buffer = []
        fuse_addr  = 0
        logger.debug(f'chunks {chunks}')   
        for d in chunks:
            rev_d = d[::-1] ## reverse
            int_d = int(rev_d,2)
            dline = fuse_addr + (1 << MTVE_GLOBALS.MTV_DUT_FUSE_ARRAY_WE_RANGE_MSB) + ( int_d << MTVE_GLOBALS.MTV_DUT_FUSE_ARRAY_WE_DATA_LSB )
            mmi_buffer.append( dline )
            fuse_addr += 1
        logger.debug(f'mmi_buffer {mmi_buffer}')
        
        for e in mmi_buffer:
            self.ConfigWr(addr=self.FUSE_REG0,data=e,burst=1)
            
        self.ConfigWr(addr=self.FUSE_REG0,data=0,burst=1)  
        logger.debug(f'Test: Finish writing fuse content')
        

    def ReadLCRom(self,mem_size=20480, burst=1):
        filename = 'dump_mem'    
        raddr = 0
        line_addr = 0
        
        with open(filename, "w") as file:
            while (raddr < mem_size):
                line_addr = raddr + (2<<16)
                self.ConfigWr(addr=self.ROM_ADDR_REG,data=line_addr,burst=1)  
                self.ConfigRd(addr=self.ROM_RDDATA_REG,burst=1)  
                rsp = yield self.resp.get()           
                logger.debug('Test: DUT LC ROM read response: %s'
                            % hex(rsp['data']))
                file.write(str(hex(rsp['data'])) + "\n") 
                raddr+=1
        
        line_addr = 0
        self.ConfigWr(addr=self.ROM_ADDR_REG,data=line_addr,burst=1)



    def WriteLCRom(self,mem_size=20480, burst=1,file_path="gbr_rom_lc_fw_irom.hex"):
        waddr = 0
        wdata = 0
                        
        try:
            with open(file_path, "r") as file:
                for line in file:
                    #Data formmating 
                    cleaned_line = line.strip()
                    wdata  = int(cleaned_line, 16)  
                    wdata_hex = hex(wdata)                            
                    logger.debug(f'Test: DUT LC ROM Addr: {waddr} Data: {wdata_hex}')                
                    self.ConfigWr(addr=self.ROM_WRDATA_REG,data=wdata,burst=1)  
                    line_addr = waddr + (3<<16)
                    self.ConfigWr(addr=self.ROM_ADDR_REG,data=line_addr,burst=1)
                    line_addr = 0
                    self.ConfigWr(addr=self.ROM_ADDR_REG,data=line_addr,burst=1)
                    waddr+=1
        except FileNotFoundError:
            logger.debug('Test: The file %s was not found.' % file_path)
       


   

    def Write_PD_XTOR_RAM(self,choose_ram="IRAM",mem_size=65536,file_path="gbr_rom_lc_fw_irom.hex"):

        waddr = 0
        wdata = 0

        burst_size=16
        
        logger.debug(f'Test: Loading PD_XTOR_{choose_ram} from file_path:{file_path} mem_size:{mem_size} burst_size:{burst_size}')
        
        try:
            with open(file_path, "r") as file:

                lines = file.readlines()

                waddr = 0;
                
                for i in range(0, min(len(lines), mem_size), burst_size): 

                    hex_values = [int(single_value.strip(), 16) for single_value in lines[i:i+burst_size]]

                    logger.debug(f'Test: PD_XTOR_{choose_ram} iteration {i} hex_values:{hex_values}')
                    
                    burst_arr = []
                    for e in hex_values:
                        burst_val = waddr + (3<<16) + (e<<32);
                        burst_arr.append(burst_val)

                    burst_len = len(burst_arr)
                        
                    logger.debug(f'Test: DUT PD_XTOR_IRAM Addr: {waddr} Len: {burst_len} Data: {burst_arr}')

                    if   choose_ram == "IRAM":
                        ram_addr = self.MTV_PD_XTOR_IRAM_START
                    elif choose_ram == "DRAM":
                        ram_addr = self.MTV_PD_XTOR_DRAM_START
                        
                    
                    self.ConfigWr(addr=ram_addr,data=burst_arr,burst=burst_len)
                    waddr+=burst_size

                burst_arr = [0x0]
                self.ConfigWr(addr=ram_addr,data=burst_arr,burst=1)
 


        except FileNotFoundError:
            logger.debug('Test: The file %s was not found.' % file_path)
       


   
