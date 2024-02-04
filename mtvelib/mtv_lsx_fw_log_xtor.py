import os
import sys
import re
import logging
import queue
import random

sys.path.append(os.environ.get("COMMON_UTIL") + "/sys_pkgs")
import simpy
from utils.mtvelib.mtv_xtor   import *
from utils.mtvelib.mtv_imports import *
from simpy.events import AnyOf, AllOf, Event
from simpy import Store


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

RxPreset  = 0
RxLocked  = 4
RxActive  = 5
ClkSwDone = 6
NewReq    = 7
TxPreset  = 16
ReqDone   = 16+6
TxActive  = 16+7
StartTx   = 16+7
PresetReq = 32

class SBRegister:
   def __init__(self, name, size_in_bytes, reset_value=None, length_is_known=True, data_is_right=True):
      self.name = name
      self.size_in_bytes = size_in_bytes
      self.length_is_known = length_is_known
      self.data_is_right = data_is_right
      if reset_value is None:
         self.reset_value = self.size_in_bytes * '00'
      else:
         if len(reset_value) != size_in_bytes*2:
            raise ValueError("Reset value size does not match the Sideband Register size")
         self.reset_value = reset_value
      self.value = self.reset_value  # Initialize value to the reset_value

   def bit(self, pos):
      length_in_bits = 8*self.size_in_bytes
      bin_value = hex2bin(self.value).zfill(length_in_bits)
      return (int(bin_value[length_in_bits - pos - 1]))
      
   def Field(self, offset, size):
      return ((int(self.value, 16) >> offset) & ((1 << size) - 1))
   
   
   def SetBit(self, bit):
      length_in_bits = 8*self.size_in_bytes
      bin_value = hex2bin(self.value).zfill(length_in_bits)
      if (bin_value[length_in_bits - bit - 1] == '0'):
         self.value = FlipBit(self.value, bit).zfill(2*self.size_in_bytes)
      
   def ClrBit(self, bit):
      length_in_bits = 8*self.size_in_bytes
      bin_value = hex2bin(self.value).zfill(length_in_bits)
      if (bin_value[length_in_bits - bit - 1] == '1'):
         self.value = FlipBit(self.value, bit).zfill(2*self.size_in_bytes)
   
   def WriteBytes(self, Data, Len):
      if (Len == self.size_in_bytes):
         self.value = hex(Data)[2:].zfill(Len*2)
      else:
         self.value = self.value[:2*(self.size_in_bytes-Len)] + hex(Data)[2:].zfill(2*Len)
         
   def SetField(self, value, offset, size):
      if len(bin(value)[2:]) > size:
         logger.debug("Value %i is bigger than the size %i of the field", value, size)
         raise ValueError("Trying to set a number too big to the field given")
      val = int(self.value, 16)
      mask = (1 << size) - 1
      val &= ~(mask << offset)
      val |= value << offset
      self.value = hex(val)[2:]
      

class LSX(mtv_xtor):
   
   
   def __init__(self, mtv, xtor_id=None, name=None):
      super().__init__(mtv, xtor_id, name)
      self.mtv = mtv
      self.xtor_id = xtor_id
      self.name = name
      self.LP_LaneParams = 0
      self.LaneParams = 0

      # Define LSX Events
      self.SBRX_Rise         = mtv.env.event()
      self.SBRX_Fall         = mtv.env.event()
      self.Got_AT_Resp       = mtv.env.event()
      self.Got_AT_RD_Resp    = mtv.env.event()
      self.Got_AT_WR_Resp    = mtv.env.event()
      self.Got_RT_Resp       = mtv.env.event()
      self.Got_BC_RT         = mtv.env.event()
      self.SBNegotiationDone = mtv.env.event()
      self.NewPresetReq      = [mtv.env.event() for _ in range(2)]
      self.PresetReqDone     = [mtv.env.event() for _ in range(2)]
      self.NoMorePresets     = [mtv.env.event() for _ in range(2)]
      self.TxActiveSet       = [mtv.env.event() for _ in range(2)]
      self.StartTxSet        = [mtv.env.event() for _ in range(2)]
      self.NewRequestSet     = [mtv.env.event() for _ in range(2)]
      self.NewRequestClr     = [mtv.env.event() for _ in range(2)]
      self.RequestDoneSet    = [mtv.env.event() for _ in range(2)]
      self.RequestDoneClr    = [mtv.env.event() for _ in range(2)]
      self.RxLocked          = [mtv.env.event() for _ in range(2)]
      self.L0_Rx_TxFFE_Done  = mtv.env.event()
      self.L1_Rx_TxFFE_Done  = mtv.env.event()
      self.L0_Tx_TxFFE_Done  = mtv.env.event()
      self.L1_Tx_TxFFE_Done  = mtv.env.event()
       
      #LSX Variables
      self.LSXAnalyzer = False
      self.fw_log      = []
#      self.Gen4TxFFE_fifo  = queue.Queue()
      self.TBT3TxFFE_fifo  = simpy.Store(mtv.env)
      self.Gen4TxFFE_fifo  = simpy.Store(mtv.env)
      self.Preset2Tx = [0, 0]
      self.RequestPreset = [0, 0]
      self.PrevPresetReq = [0, 0]
      self.TBT3TxFFE_Transmitter_Done = [False, False]
      self.PartnerFinishedTxFFE = 0
      self.RT_Txn_IP = 0
      self.AT_Txn_IP = 0
      self.PollTxFFE = 3 # TEMP Need to be 1000-5000
      self.SBRX_State = 'Low'
      self.LinkType = {
         'Link'     : 'USB4',
         'Gen'      : 4,
         'Sideband' : 'USB4',
         'RS_FEC'   : True,
         'SSCOA'    : False,
         'Asym3Tx'  : False,
         'Asym3Rx'  : False,
         'L0En'     : True,
         'L1En'     : True,
         'Bonding'  : True,
         'LinkUp'   : False
      }


      self.SBRegSpace = {
         0 : SBRegister("VendorId",   4,  '80861234'), #TEMP
         1 : SBRegister("ProductId",  4,  'AABBCCDD'), #TEMP
         5 : SBRegister("DebugCfg",   4),
         6 : SBRegister("Debug",      54),
         7 : SBRegister("LRDTuning",  4),
         8 : SBRegister("Opcode",     4),
         9 : SBRegister("Metadata",   4),
         10: SBRegister("Reserved",   4),
         12: SBRegister("LinkCfg",    3,  '1FF300', ),
         13: SBRegister("Gen23TxFFE", 4),
         14: SBRegister("Gen4TxFFE",  4),
         15: SBRegister("SBVer",      4,  '00040002'),
         16: SBRegister("VenDef1",    4),
         17: SBRegister("VenDef2",    4),
         18: SBRegister("Data",       64),
         98: SBRegister("VSEC",       64)
      }
   
      self.PartnerSBRegSpace = {
         0 : SBRegister("VendorId",   4,  data_is_right=False),
         1 : SBRegister("ProductId",  4,  data_is_right=False),
         5 : SBRegister("DebugCfg",   4,  data_is_right=False),
         6 : SBRegister("Debug",      54, data_is_right=False),
         7 : SBRegister("LRDTuning",  4,  data_is_right=False),
         8 : SBRegister("Opcode",     4,  data_is_right=False),
         9 : SBRegister("Metadata",   4,  data_is_right=False),
         10: SBRegister("Reserved",   4,  data_is_right=False),
         12: SBRegister("LinkCfg",    3,  data_is_right=False),
         13: SBRegister("Gen23TxFFE", 4,  data_is_right=False, length_is_known=False),
         14: SBRegister("Gen4TxFFE",  4,  data_is_right=False),
         15: SBRegister("SBVer",      4,  data_is_right=False),
         16: SBRegister("VenDef1",    4,  data_is_right=False, length_is_known=False),
         17: SBRegister("VenDef2",    4,  data_is_right=False, length_is_known=False),
         18: SBRegister("Data",       64, data_is_right=False),
         98: SBRegister("VSEC",       64, data_is_right=False, length_is_known=False)
      }
      
      #Initializing Receiver
      self.RX = self.mtv.env.process(self.Receiver())
      self.TxFFE = self.mtv.env.process(self.TxFFE_manager(AggregateTxns=False))
      self.TxFFEReader = self.mtv.env.process(self.Gen23TxFFE_Reader())
      
   def ChangeCapabilities(self, capabilities):
      
      Reg12Bin = hex2bin(self.SBRegSpace[12].value)
      for capability, value in capabilities.items():
         logger.debug('Test: LSX[%s] - Capability %s is changed to %s', self.name[-1], capability, value)
         if capability == 'L1En':
            if (int(value) != int(Reg12Bin[-9])):
               logger.debug('Test: LSX[%s] - Flipping bit 9. Value before the flip: %s,Value after the flip: %s', self.name[-1], self.SBRegSpace[12].value, FlipBit(self.SBRegSpace[12].value, 9))
               self.SBRegSpace[12].value = FlipBit(self.SBRegSpace[12].value, 9)
         elif capability == 'Gen3Support':
            if (int(value) != int(Reg12Bin[-13])):
               logger.debug('Test: LSX[%s] - Flipping bit 13. Value before the flip: %s,Value after the flip: %s', self.name[-1], self.SBRegSpace[12].value, FlipBit(self.SBRegSpace[12].value, 13))
               self.SBRegSpace[12].value = FlipBit(self.SBRegSpace[12].value, 13)
         elif capability == 'Gen2RSFEC':
            if (int(value) != int(Reg12Bin[-14])):
               logger.debug('Test: LSX[%s] - Flipping bit 14. Value before the flip: %s,Value after the flip: %s', self.name[-1], self.SBRegSpace[12].value, FlipBit(self.SBRegSpace[12].value, 14))
               self.SBRegSpace[12].value = FlipBit(self.SBRegSpace[12].value, 14)
         elif capability == 'Gen3RSFEC':
            if (int(value) != int(Reg12Bin[-15])):
               logger.debug('Test: LSX[%s] - Flipping bit 15. Value before the flip: %s,Value after the flip: %s', self.name[-1], self.SBRegSpace[12].value, FlipBit(self.SBRegSpace[12].value, 15))
               self.SBRegSpace[12].value = FlipBit(self.SBRegSpace[12].value, 15)
         elif capability == 'USB4SB':
            if (int(value) != int(Reg12Bin[-16])):
               logger.debug('Test: LSX[%s] - Flipping bit 16. Value before the flip: %s,Value after the flip: %s', self.name[-1], self.SBRegSpace[12].value, FlipBit(self.SBRegSpace[12].value, 16))
               self.SBRegSpace[12].value = FlipBit(self.SBRegSpace[12].value, 16)
         elif capability == 'TBT3Support':
            if (int(value) != int(Reg12Bin[-17])):
               logger.debug('Test: LSX[%s] - Flipping bit 17. Value before the flip: %s,Value after the flip: %s', self.name[-1], self.SBRegSpace[12].value, FlipBit(self.SBRegSpace[12].value, 17))
               self.SBRegSpace[12].value = FlipBit(self.SBRegSpace[12].value, 17)
         elif capability == 'Gen4Support':
            if (int(value) != int(Reg12Bin[-18])):
               logger.debug('Test: LSX[%s] - Flipping bit 18. Value before the flip: %s,Value after the flip: %s', self.name[-1], self.SBRegSpace[12].value, FlipBit(self.SBRegSpace[12].value, 18))
               self.SBRegSpace[12].value = FlipBit(self.SBRegSpace[12].value, 18)
         elif capability == 'Asym3TxSupport':
            if (int(value) != int(Reg12Bin[-19])):
               logger.debug('Test: LSX[%s] - Flipping bit 19. Value before the flip: %s,Value after the flip: %s', self.name[-1], self.SBRegSpace[12].value, FlipBit(self.SBRegSpace[12].value, 19))
               self.SBRegSpace[12].value = FlipBit(self.SBRegSpace[12].value, 19)
         elif capability == 'Asym3RxSupport':
            if (int(value) != int(Reg12Bin[-20])):
               logger.debug('Test: LSX[%s] - Flipping bit 20. Value before the flip: %s,Value after the flip: %s', self.name[-1], self.SBRegSpace[12].value, FlipBit(self.SBRegSpace[12].value, 20))
               self.SBRegSpace[12].value = FlipBit(self.SBRegSpace[12].value, 20)
         elif capability == 'Asym3TxRequest':
            if (int(value) != int(Reg12Bin[-21])):
               logger.debug('Test: LSX[%s] - Flipping bit 21. Value before the flip: %s,Value after the flip: %s', self.name[-1], self.SBRegSpace[12].value, FlipBit(self.SBRegSpace[12].value, 21))
               self.SBRegSpace[12].value = FlipBit(self.SBRegSpace[12].value, 21)
         elif capability == 'Asym3RxRequest':
            if (int(value) != int(Reg12Bin[-22])):
               logger.debug('Test: LSX[%s] - Flipping bit 22. Value before the flip: %s,Value after the flip: %s', self.name[-1], self.SBRegSpace[12].value, FlipBit(self.SBRegSpace[12].value, 22))
               self.SBRegSpace[12].value = FlipBit(self.SBRegSpace[12].value, 22)
         else:
            logger.debug('Test: LSX[%s] - Capability %s does not exist', self.name[-1], capability)
            raise ValueError("Capability does not exist")
      logger.debug('Test: LSX[%s] - The new value of register 12 is %s', self.name[-1], self.SBRegSpace[12].value)
      
   
      
   def LaneInit(self):
      yield from self.SidebandNegotiation(fast=True)
      
      # Need to get indication from High-Speed that Rx and Tx are active
      self.LinkType['LinkUp'] = True
         
      if self.LinkType['L0En']:
         if self.LinkType['Gen'] == 4:
            L0_TxFFE_Rx = self.mtv.env.process(self.Gen4TxFFE_Receiver(0))
            L0_TxFFE_Tx = self.mtv.env.process(self.Gen4TxFFE_Transmitter(0))
         elif (self.LinkType['Sideband'] == 'USB4'):
            L0_TxFFE_Rx = self.mtv.env.process(self.Gen23TxFFE_Receiver(0))
            L0_TxFFE_Tx = self.mtv.env.process(self.Gen23TxFFE_Transmitter(0))
         else:
            L0_TxFFE_Rx = self.mtv.env.process(self.TBT3TxFFE_Receiver(0))
            L0_TxFFE_Tx = self.mtv.env.process(self.TBT3TxFFE_Transmitter(0))

      else:
         L0_TxFFE_Tx = self.mtv.env.event()
         L0_TxFFE_Tx.succeed()
         L0_TxFFE_Rx = self.mtv.env.event()
         L0_TxFFE_Rx.succeed()
         
      if self.LinkType['L1En']:
         if self.LinkType['Gen'] == 4:
            L1_TxFFE_Rx = self.mtv.env.process(self.Gen4TxFFE_Receiver(1))
            L1_TxFFE_Tx = self.mtv.env.process(self.Gen4TxFFE_Transmitter(1))
         elif (self.LinkType['Sideband'] == 'USB4'):
            L1_TxFFE_Rx = self.mtv.env.process(self.Gen23TxFFE_Receiver(1))
            L1_TxFFE_Tx = self.mtv.env.process(self.Gen23TxFFE_Transmitter(1))
         else:
            logger.debug("TBT3 TxFFE still not implemented.")
      else:
         L1_TxFFE_Tx = self.mtv.env.event()
         L1_TxFFE_Tx.succeed()
         L1_TxFFE_Rx = self.mtv.env.event()
         L1_TxFFE_Rx.succeed()
      
      yield AllOf(self.mtv.env, [L0_TxFFE_Tx, L0_TxFFE_Rx, L1_TxFFE_Tx, L1_TxFFE_Rx])
     
 

   # Status variables
   
   def Receiver(self):
      """"""
    
      #Initial values
      connect_cmd    = 0xdeadbeef
      disconenct_cmd = 0xbeefdead
      fw_log_type    = 255
      sbrx_type      = 64
      cmd_type       = 128
      rsp_type       = 256
      bc_type        = 512         
      lt_type        = 1024

      while not self.LSXAnalyzer:
         resp = yield self.UPSTREAM_FIFO.get() # wait for message on UpstreamFIFO
         while (resp['resp_type'] == 0):
            resp = yield self.UPSTREAM_FIFO.get() # wait for message on UpstreamFIFO
    
         if (resp['resp_type'] == cmd_type):
            logger.debug('Test: LSX[%s] Command is %s', self.name[-1], resp)
            self.ReceiveCmd(resp)
          
            
         elif (resp['resp_type'] == rsp_type):
            logger.debug('Test: LSX[%s] Response is %s', self.name[-1], resp)
            self.ReceiveRsp(resp)


         elif (resp['resp_type'] == bc_type):
            logger.debug('Test: LSX[%s] Broadcast RT Transaction is %s', self.name[-1], resp)
            self.LP_LaneParams = self.ReceiveBc(resp)
          
         elif (resp['resp_type'] == sbrx_type):
            if (resp['data'] == connect_cmd):
               logger.debug('Test: LSX[%s] detected SBRX high' % self.name[-1])
               self.SBRX_State = 'High'
               self.SBRX_Rise.succeed()
               self.SBRX_Fall = self.mtv.env.event()
            if (resp['data'] == disconenct_cmd):
               logger.debug('Test: LSX[%s] Detected SBRX Low', self.name[-1])
               self.SBRX_State = 'Low'
               self.SBRX_Fall.succeed()
               self.SBRX_Rise = self.mtv.env.event()

      while self.LSXAnalyzer:
         resp = yield self.UPSTREAM_FIFO.get() # wait for message on UpstreamFIFO
         while (resp['resp_type'] == 0):
            resp = yield self.UPSTREAM_FIFO.get() # wait for message on UpstreamFIFO
    
         if (resp['resp_type'] == fw_log_type):
            self.ReceiveFwLog(resp)
         elif (resp['resp_type'] == sbrx_type):
            if (resp['data'] == connect_cmd):
               logger.debug('Test: LSX[%s] detected SBRX high' % self.name[-1])
               self.SBRX_State = 'High'
               self.SBRX_Rise.succeed()
               self.SBRX_Fall = self.mtv.env.event()
            if (resp['data'] == disconenct_cmd):
               logger.debug('Test: LSX[%s] Detected SBRX Low', self.name[-1])
               self.SBRX_State = 'Low'
               self.SBRX_Fall.succeed()
               self.SBRX_Rise = self.mtv.env.event()
            
            

   def Gen23TxFFE_Reader(self):
      yield self.SBNegotiationDone
      logger.debug('LSX[%s] Link Up Status: %s', self.name[-1], self.LinkType['LinkUp'])
      if (self.LinkType['Gen'] < 4) and (self.LinkType['Sideband'] == 'USB4'):
         while True:
            logger.debug('LSX[%s] Initiating an RT Read Command to check its Link Partner status', self.name[-1])
            if (self.RT_Txn_IP == 1):
               yield self.Got_RT_Resp
               yield self.mtv.env.timeout(1)
            self.TxRtRdCmd(Index=0, Reg=13, Len=4)
            yield self.Got_RT_Resp
            TxTxFFEDone = ((self.PartnerSBRegSpace[13].bit(4) == 1) or not self.LinkType['L0En']) and ((self.PartnerSBRegSpace[13].bit(11) == 1) or not self.LinkType['L1En'])
            RxTxFFEDone = (self.NoMorePresets[0] or not self.LinkType['L0En']) and (self.NoMorePresets[1] or not self.LinkType['L1En'])
            if TxTxFFEDone and RxTxFFEDone:
               logger.debug('LSX[%s] has finished TxFFE in both RX and TX.', self.name[-1])
               break
            else:
               yield self.mtv.set_timer(us=self.PollTxFFE)
      elif (self.LinkType['Sideband'] == 'TBT3'):
         self.PartnerSBRegSpace[13] = SBRegister("Gen23TxFFE", 8,  data_is_right=False, length_is_known=True)
         while True:
            logger.debug('LSX[%s] Initiating an AT Read Command to check its Link Partner status', self.name[-1])
            if (self.AT_Txn_IP == 1):
               yield self.Got_AT_Resp
            self.TBT3TxFFE_fifo.put({'Read':True})
            yield self.Got_AT_RD_Resp
            TxTxFFEDone = ((self.PartnerSBRegSpace[13].bit(4) == 1) or not self.LinkType['L0En']) and ((self.PartnerSBRegSpace[13].bit(11) == 1) or not self.LinkType['L1En'])
            RxTxFFEDone = (self.NoMorePresets[0] or not self.LinkType['L0En']) and (self.NoMorePresets[1] or not self.LinkType['L1En'])
            if TxTxFFEDone and RxTxFFEDone:
               logger.debug('LSX[%s] has finished TxFFE in both RX and TX.', self.name[-1])
               break
            else:
               yield self.mtv.set_timer(us=self.PollTxFFE)
         



   def TxFFE_manager(self, AggregateTxns):
      while True:
         if (len(self.Gen4TxFFE_fifo.items) > 0):
            if (self.RT_Txn_IP == 1):
               yield self.Got_RT_Resp
            while (len(self.Gen4TxFFE_fifo.items) > 0):
               Gen4TxFFEReg_Req = yield self.Gen4TxFFE_fifo.get()
               Lane = Gen4TxFFEReg_Req['Lane']
               if Gen4TxFFEReg_Req['SetNewReq']:
                  self.PartnerSBRegSpace[14].SetBit(NewReq+8*Lane)
                  self.PartnerSBRegSpace[14].SetField(Gen4TxFFEReg_Req['ReqPreset'], 8*Lane, 6)
                  logger.debug('LSX[%s] Lane %i setting New Request with Preset %i.', self.name[-1], Lane, Gen4TxFFEReg_Req['ReqPreset'])
               if Gen4TxFFEReg_Req['ClrNewReq']:
                  self.PartnerSBRegSpace[14].ClrBit(NewReq+8*Gen4TxFFEReg_Req['Lane'])
                  logger.debug('LSX[%s] Lane %i clearing New Request.', self.name[-1], Lane)
               if Gen4TxFFEReg_Req['SetReqDone']:
                  self.PartnerSBRegSpace[14].SetBit(ReqDone+8*Gen4TxFFEReg_Req['Lane'])
                  self.PartnerSBRegSpace[14].SetField(Gen4TxFFEReg_Req['PresetSet'], TxPreset+8*Gen4TxFFEReg_Req['Lane'], 6)
                  logger.debug('LSX[%s] Lane %i setting Request Done with Preset %i.', self.name[-1], Lane, Gen4TxFFEReg_Req['PresetSet'])
               if Gen4TxFFEReg_Req['ClrReqDone']:
                  self.PartnerSBRegSpace[14].ClrBit(ReqDone+8*Gen4TxFFEReg_Req['Lane'])
                  logger.debug('LSX[%s] Lane %i clearing Request Done.', self.name[-1], Lane)
               if Gen4TxFFEReg_Req['StartTx']:
                  self.PartnerSBRegSpace[14].SetBit(StartTx+8*Gen4TxFFEReg_Req['Lane'])
                  logger.debug('LSX[%s] Lane %i setting Start TxFFE.', self.name[-1], Lane)
               if not AggregateTxns:
                  break

            Data2Wr = int(self.PartnerSBRegSpace[14].value, 16)
            logger.debug('LSX[%s] Data to write to Register 14 is 0x%s.', self.name[-1], self.PartnerSBRegSpace[14].value)
            if (self.RT_Txn_IP == 1):
               yield self.Got_RT_Resp
            self.TxRtWrCmd(Index=0, Reg=14, Len=4, Data=Data2Wr)
               
         if (len(self.TBT3TxFFE_fifo.items) > 0):
            if (self.AT_Txn_IP == 1):
               yield self.Got_AT_Resp
            while (len(self.TBT3TxFFE_fifo.items) > 0):
               TBT3TxFFEReg_Req = yield self.TBT3TxFFE_fifo.get()
               if TBT3TxFFEReg_Req['Read']:
                  self.TxAtRdCmd(Reg=13, Len=8)
               else:
                  Lane = TBT3TxFFEReg_Req['Lane']
                  if TBT3TxFFEReg_Req['SetNewReq']:
                     self.PartnerSBRegSpace[13].SetBit(32+NewReq+8*Lane)
                     self.PartnerSBRegSpace[13].SetField(TBT3TxFFEReg_Req['ReqPreset'], 32+8*Lane, 4)
                     logger.debug('LSX[%s] Lane %i setting New Request with Preset %i.', self.name[-1], Lane, TBT3TxFFEReg_Req['ReqPreset'])
                  if TBT3TxFFEReg_Req['ClrNewReq']:
                     self.PartnerSBRegSpace[13].ClrBit(32+NewReq+8*Lane)
                     logger.debug('LSX[%s] Lane %i clearing New Request.', self.name[-1], Lane)
                  if TBT3TxFFEReg_Req['SetReqDone']:
                     self.PartnerSBRegSpace[13].SetBit32+(ReqDone+8*Lane)
                     self.PartnerSBRegSpace[13].SetField(TBT3TxFFEReg_Req['PresetSet'], 32+TxPreset+8*Lane, 6)
                     logger.debug('LSX[%s] Lane %i setting Request Done with Preset %i.', self.name[-1], Lane, TBT3TxFFEReg_Req['PresetSet'])
                  if TBT3TxFFEReg_Req['ClrReqDone']:
                     self.PartnerSBRegSpace[13].ClrBit(32+ReqDone+8*Lane)
                     logger.debug('LSX[%s] Lane %i clearing Request Done.', self.name[-1], Lane)
                  if TBT3TxFFEReg_Req['TxActiveSet']:
                     self.PartnerSBRegSpace[13].SetBit(32+TxActive+8*Lane)
                     logger.debug('LSX[%s] Lane %i Setting Tx Active in Link Partner.', self.name[-1], Lane)
                  if not AggregateTxns:
                     break
   
                  if not TBT3TxFFEReg_Req['Wait4Tx']:
                     Data2Wr = int(self.PartnerSBRegSpace[13].value, 16)
                     logger.debug('LSX[%s] Transmitter finished TxFFE. Data to write to Register 13 is 0x%s.', self.name[-1], self.PartnerSBRegSpace[13].value)
                     if (self.AT_Txn_IP == 1):
                        yield self.Got_AT_Resp
                     self.TxAtWrCmd(Reg=13, Len=8, Data=Data2Wr)
                  else:
                     yield self.Got_AT_WR_Resp
                     
         yield self.mtv.env.timeout(1)
            

   
   def SidebandNegotiation(self, fast=False):
      """"""
      
      logger.debug('Test: Writing SBTX high')    
      self.Ctrl0Wr(setSBTX=1, clrSBTX=0)
      yield self.SBRX_Rise
      logger.debug('Test: LSX[%s] state is %s', self.name[-1], self.SBRX_State)
      if not fast:
         logger.debug('Test: LSX[%s] Reading Register 0xA', self.name[-1])
         self.TxAtRdCmd(Reg=0xD, Len=4)
         yield self.Got_AT_Resp
         logger.debug('Test: LSX[%s] AT Transaction finished, reading again Register 0xA', self.name[-1])
         self.TxAtRdCmd(Reg=0xD, Len=4)
         yield self.Got_AT_Resp
         logger.debug('Test: LSX[%s] AT Transaction finished, reading  Register 0xC', self.name[-1])
         
      self.TxAtRdCmd(Reg=0xC, Len=3)
      yield self.Got_AT_Resp
      logger.debug('Test: LSX[%s] This is the content of the Link Partner Register 12 (0xC): %s', self.name[-1], self.PartnerSBRegSpace[12].value)
      logger.debug('Test: LSX[%s] AT Transaction finished, checking capabilities of Link Partner...', self.name[-1])

      SelfCapabilities = self.ParseReg12(self.SBRegSpace)
      LinkPartnerCapabilities = self.ParseReg12(self.PartnerSBRegSpace)
    
      logger.debug('Test: LSX[%s] These are the capabilities of the Link Partner: %s', self.name[-1], LinkPartnerCapabilities)
      logger.debug('Test: LSX[%s] These are the capabilities of the Router under test: %s', self.name[-1], SelfCapabilities)
      self.CapabilitieNegotiation(SelfCapabilities, LinkPartnerCapabilities)
      
      if fast:
         bc_rt_sent = 1
      else:
         bc_rt_sent = 0
         
      while True:
         logger.debug('Test: LSX[%s] time %d - Transmitting BC RT Transaction with the following Lane Parameters: %s', self.name[-1], self.mtv.env.now, self.LinkType)
         self.TxRtBcCmd(Index=0, CRC=0)
         bc_rt_sent += 1
         wait2ms = self.mtv.set_timer(us=10)
         yield AnyOf(self.mtv.env, [self.Got_BC_RT, wait2ms])
         if (self.Got_BC_RT.triggered) & (bc_rt_sent > 1):
            break
         else:
            yield wait2ms
        
      if self.LP_LaneParams != self.LaneParams: # TEMP only for Symmetric Link
         logger.debug('Test: ERROR LSX[%s] The Broadcasr RT Transaction that was sent %s was not equal to the Broadcast RT Transaction that was received %s', self.name[-1], hex(self.LP_LaneParams), hex(self.LaneParams))
         self.SBNegotiationDone.fail()
         raise ValueError("Sideband Negotiation Failed.")
      else:
         logger.debug('Test: LSX[%s] The Broadcasr RT Transaction that was sent %s is equal to the Broadcast RT Transaction that was received %s', self.name[-1], hex(self.LP_LaneParams), hex(self.LaneParams))
 
      logger.debug('Test: LSX[%s] Continue to activate High-Speed with the following Link Type:', self.name[-1])
      logger.debug('%s', self.LinkType)
      
      binaryReg12 = int(self.SBRegSpace[12].value, 16)
      binaryReg12 = binaryReg12 | (int(self.LinkType['L0En'])) | ((int(self.LinkType['L1En'])) << 1) | ((int(self.LinkType['Asym3Tx'])) << 2) | ((int(self.LinkType['Asym3Rx'])) << 3)
      self.SBRegSpace[12].value = hex(binaryReg12)[2:].zfill(6)
      
      self.SBNegotiationDone.succeed() 
            

   def TBT3TxFFE_Receiver(self, Lane=0):
      logger.debug('LSX[%s] RX TxFFE Lane %i waiting for Tx Active bit on the Link Partner to be set.', self.name[-1], Lane)
      yield self.TxActiveSet[Lane]
      logger.debug('LSX[%s] RX TxFFE Lane %i Actiavting receiver and setting Rx Active.', self.name[-1], Lane)
      self.SBRegSpace[13].SetBit(RxActive+Lane*8)
      while True:
         #Evaluate RX Signal
         yield AnyOf(self.mtv.env, [self.NewPresetReq[Lane], self.NoMorePresets[Lane]])
         if self.NoMorePresets[Lane].triggered:
            break

         self.NewPresetReq[Lane] = self.mtv.env.event()
         logger.debug('LSX[%s] RX TxFFE Lane %i Got new Preset from PHY, setting New Request and Preset on Link Partner Register', self.name[-1], Lane)
         Wait4Tx = not self.TBT3TxFFE_Transmitter_Done
         TBT3TxFFEReg = {'Read':False, 'Lane':Lane, 'SetNewReq':True, 'ClrNewReq':False, 'ReqPreset':self.RequestPreset[Lane], 'SetReqDone':False, 'ClrReqDone':False, 'PresetSet':0, 'Wait4Tx':Wait4Tx, 'RxLockedSet':False, 'TxActiveSet':False}
         self.TBT3TxFFE_fifo.put(TBT3TxFFEReg)
         yield self.Got_AT_Resp
         #Evaluate RX Signal
         TBT3RxLocked = self.NoMorePresets[Lane].triggered
         Wait4Tx = not (self.TBT3TxFFE_Transmitter_Done[0] and self.TBT3TxFFE_Transmitter_Done[1])
         TBT3TxFFEReg = {'Read':False, 'Lane':Lane, 'SetNewReq':False, 'ClrNewReq':not TBT3RxLocked, 'ReqPreset':self.RequestPreset[Lane], 'SetReqDone':False, 'ClrReqDone':False, 'PresetSet':0, 'Wait4Tx':Wait4Tx, 'RxLockedSet':TBT3RxLocked, 'TxActiveSet':False}
         self.TBT3TxFFE_fifo.put(TBT3TxFFEReg)
         yield self.Got_AT_Resp
         
         
         
   def TBT3TxFFE_Transmitter(self, Lane=0):
      self.SBRegSpace[13].SetBit(TxActive+8*Lane)
      logger.debug('LSX[%s] TX TxFFE Lane %i Setting Tx Active bit in the Port.', self.name[-1], Lane)
      TBT3TxFFEReg = {'Read':False, 'Lane':Lane, 'SetNewReq':False, 'ClrNewReq':False, 'ReqPreset':0, 'SetReqDone':False, 'ClrReqDone':False, 'PresetSet':0, 'Wait4Tx':False, 'RxLockedSet':False, 'TxActiveSet':True}
      self.TBT3TxFFE_fifo.put(TBT3TxFFEReg)
      logger.debug('LSX[%s] TX TxFFE Lane %i Setting Tx Active bit in the Port of the Link Partner.', self.name[-1], Lane)
      while True:
         if (self.PartnerSBRegSpace[13].bit(RxLocked+8*Lane) == 1):
            logger.debug('LSX[%s] TX TxFFE Lane %i Rx Locked is set in the Link Partner, Transmitter TxFFE is done.', self.name[-1], Lane)
            self.TBT3TxFFE_Transmitter_Done[Lane] = True
            break
         yield self.Got_AT_Resp
         if (self.PartnerSBRegSpace[13].bit(NewReq+8*Lane) == 1) or (self.PartnerSBRegSpace[13].Field(PresetReq + 8*Lane, 4) != self.PrevPresetReq[Lane]):
            self.PrevPresetReq[Lane] = self.PartnerSBRegSpace[13].Field(PresetReq + 8*Lane, 4)
            #send requested Preset to High-Speed
            RandDelay = self.mtv.set_timer(ns=random.randint(0, 100)) # TEMP
            yield RandDelay
            #Get indication from High-Speed that Preset is used
            self.TransmitterPresetLoaded[Lane] = 1
            while (self.TransmitterPresetLoaded[0] + self.TransmitterPresetLoaded[1]) < 2:
               yield self.mtv.env.timeout(1)
            
            TBT3TxFFEReg = {'Read':False, 'Lane':Lane, 'SetNewReq':False, 'ClrNewReq':False, 'ReqPreset':0, 'SetReqDone':False, 'ClrReqDone':False, 'PresetSet':self.PrevPresetReq[Lane], 'Wait4Tx':False, 'RxLockedSet':False, 'TxActiveSet':True}
            self.TBT3TxFFE_fifo.put(TBT3TxFFEReg)
            yield self.Got_AT_Resp
            while (PartnerSBRegSpec[13].bit(NewReq) == 1) and (PartnerSBRegSpec[13].Field(PresetReq + 8*Lane, 4) == self.PrevPresetReq[Lane]):
               yield self.Got_AT_Resp
            

      
   def Gen23TxFFE_Receiver(self, Lane=0):
      logger.debug('LSX[%s] RX TxFFE Lane %i waiting for Tx Active bit on the Link Partner to be set.', self.name[-1], Lane)
      yield self.TxActiveSet[Lane]
      
      logger.debug('LSX[%s] RX TxFFE Lane %i Tx Active bit on the Link Partner is set. Setting Rx Active bit', self.name[-1], Lane)
      self.SBRegSpace[13].SetBit(RxActive+8*Lane)

      while True:
         yield AnyOf(self.mtv.env, [self.NewPresetReq[Lane], self.NoMorePresets[Lane]])
         if self.NoMorePresets[Lane].triggered:
            break

         self.NewPresetReq[Lane] = self.mtv.env.event()
         logger.debug('LSX[%s] RX TxFFE Lane %i Got new Preset from PHY, setting New Request and Preset', self.name[-1], Lane)
         self.SBRegSpace[13].SetField(self.RequestPreset[Lane], RxPreset+8*Lane, 4)
         self.SBRegSpace[13].SetBit(NewReq+8*Lane)

         yield self.RequestDoneSet[Lane]
         if not (self.PartnerSBRegSpace[13].Field(TxPreset+8*Lane, 4) == self.RequestPreset[Lane]):
            raise ValueError("LSX[%s] Lane %i Requested Preset was not set by the Link Partner", self.name[-1], Lane)
            
         logger.debug('LSX[%s] RX TxFFE Lane %i Link Partner set Request Done with the requested Preset. Clearing New Request', self.name[-1], Lane)
         self.SBRegSpace[13].ClrBit(NewReq+8*Lane)
         yield self.RequestDoneClr[Lane]

         logger.debug('LSX[%s] RX TxFFE Lane %i Request Done was cleared. can move to next Preset', self.name[-1], Lane)
         self.PresetReqDone[Lane].succeed()
         
      logger.debug('LSX[%s] RX TxFFE Lane %i Finished TxFFE and setting RX Locked and Clock Switch Done', self.name[-1], Lane)
      self.SBRegSpace[13].SetBit(RxLocked+8*Lane)
      self.SBRegSpace[13].SetBit(ClkSwDone+8*Lane)
      


   def Gen23TxFFE_Transmitter(self, Lane=0):
      
      logger.debug('LSX[%s] TX TxFFE Lane %i Set Tx Active bit', self.name[-1], Lane)
      self.SBRegSpace[13].SetBit(TxActive+8*Lane)
      PresetRequested = 0
      logger.debug('LSX[%s] TX TxFFE Lane %i Waiting for first RT Read Response', self.name[-1], Lane)
#      yield self.Got_RT_Resp
#      logger.debug('LSX[%s] TX TxFFE got first RT Read Response', self.name[-1])
      while True:
         yield AnyOf(self. mtv.env, [self.NewRequestSet[Lane], self.RxLocked[Lane]])
         if (self.PartnerSBRegSpace[13].bit(RxLocked+8*Lane) == 1):
            logger.debug('LSX[%s] TX TxFFE Lane %i Finished TxFFE, no more requested from receiver', self.name[-1], Lane)
            return PresetRequested
            
         logger.debug('LSX[%s] TX TxFFE Lane %i Still not Rx Locked', self.name[-1], Lane)         
         logger.debug('LSX[%s] TX TxFFE Lane %i Got new Preset request from its Link Partner', self.name[-1], Lane)
         PresetRequested = self.PartnerSBRegSpace[13].Field(RxPreset+8*Lane, 4)
         #send requested Preset to High-Speed
         RandDelay = self.mtv.set_timer(ns=random.randint(0, 100)) # TEMP
         yield RandDelay
         #Get indication from High-Speed that Preset is used
         logger.debug('LSX[%s] TX TxFFE Lane %i Requested Preset is used on transmitter, setting Request Done and Preset', self.name[-1], Lane)
         self.SBRegSpace[13].SetField(PresetRequested, TxPreset+8*Lane, 4)
         self.SBRegSpace[13].SetBit(ReqDone+Lane*8)
         logger.debug('LSX[%s] TX TxFFE Lane %i Waiting for New Request to be cleared in the Link Partner', self.name[-1], Lane)
         yield self.NewRequestClr[Lane]

         logger.debug('LSX[%s] TX TxFFE Lane %i New Request is cleared, clearing Request Done', self.name[-1], Lane)
         self.SBRegSpace[13].ClrBit(ReqDone+Lane*8)
               
            
   def Gen4TxFFE_Receiver(self, Lane=0):
      Timeout = 0
      logger.debug('LSX[%s] RX TxFFE Lane %i waiting for Start TxFFE bit to be set. Register 14 is %s.', self.name[-1], Lane, self.SBRegSpace[14].value)
      yield self.StartTxSet[Lane]
      
      logger.debug('LSX[%s] RX TxFFE Lane %i Starting Receiver TxFFE.', self.name[-1], Lane)
      
      while True:
         logger.debug('LSX[%s] RX TxFFE of Lane %i has not finished TxFFE.', self.name[-1], Lane)
               
         yield AnyOf(self.mtv.env, [self.NewPresetReq[Lane], self.NoMorePresets[Lane]])
         if self.NoMorePresets[Lane].triggered:
            break
         
         self.NewPresetReq[Lane] = self.mtv.env.event()
         logger.debug('LSX[%s] RX TxFFE Need to send a Preset request to Link Partner TX of Lane %i.', self.name[-1], Lane)
         Gen4TxFFEReg = {'Lane':Lane, 'StartTx':False, 'SetNewReq':True, 'ClrNewReq':False, 'ReqPreset':self.RequestPreset[Lane], 'SetReqDone':False, 'ClrReqDone':False, 'PresetSet':0}
         self.Gen4TxFFE_fifo.put(Gen4TxFFEReg)
         
         yield self.RequestDoneSet[Lane]
         
         if (self.SBRegSpace[14].Field(TxPreset+8*Lane, 6) == self.RequestPreset[Lane]):
            logger.debug('LSX[%s] RX TxFFE Lane %i received Preset Request Done. Clearing New Request.', self.name[-1], Lane)
            Gen4TxFFEReg = {'Lane':Lane, 'StartTx':False, 'SetNewReq':False, 'ClrNewReq':True, 'ReqPreset':self.RequestPreset[Lane], 'SetReqDone':False, 'ClrReqDone':False, 'PresetSet':0}
            self.Gen4TxFFE_fifo.put(Gen4TxFFEReg)
         else:
            raise ValueError("Requested Preset was not set by the Link Partner")

         logger.debug("LSX[%s] RX TxFFE Waiting for clearing of Request Done", self.name[-1])
         yield self.RequestDoneClr[Lane]
         self.PresetReqDone[Lane].succeed()
         
      logger.debug('LSX[%s] RX TxFFE of Lane %i has finished.', self.name[-1], Lane)
      if (Lane == 0):
         self.L0_Rx_TxFFE_Done.succeed()
      else:
         self.L1_Rx_TxFFE_Done.succeed()
         


   def Gen4TxFFE_Transmitter(self, Lane=0):
      #Need to get indication from High-Speed before setting the TX Active
      RandDelay = self.mtv.set_timer(ns=random.randint(0, 400)) # TEMP
      yield RandDelay         
      
      logger.debug('LSX[%s] TX TxFFE Lane %i is enabled. Setting relevant TX Active bit.', self.name[-1], Lane)
      self.SBRegSpace[13].SetBit(23+8*Lane)

      # Need to set Start TxFFE bit in the Partner
      logger.debug('LSX[%s] TX TxFFE Setting Start TxFFE bit of Lane %i.', self.name[-1], Lane)
      Gen4TxFFEReg = {'Lane':Lane, 'StartTx':True, 'SetNewReq':False, 'ClrNewReq':False, 'ReqPreset':0, 'SetReqDone':False, 'ClrReqDone':False, 'PresetSet':0}
      self.Gen4TxFFE_fifo.put(Gen4TxFFEReg)
      
      while True:
         logger.debug("LSX[%s] TX TxFFE Waiting for setting of New Request.", self.name[-1])
         while True:
            if (self.SBRegSpace[14].bit(NewReq+8*Lane) == 1) or (self.PartnerFinishedTxFFE == 1): # Waiting for New Request or LP TxFFE Done
               break
            yield self.mtv.env.timeout(1)
         
         if (self.PartnerFinishedTxFFE == 1):
            break
         
         PresetRequested = self.SBRegSpace[14].Field(Lane*8, 6)
         logger.debug('LSX[%s] TX TxFFE Lane %i Got a New Request to Preset %i.', self.name[-1], Lane, PresetRequested)
         #send requested Preset to High-Speed
         RandDelay = self.mtv.set_timer(ns=random.randint(0, 100)) # TEMP
         yield RandDelay         
         #Get indication from High-Speed that Preset is used
      
         logger.debug('LSX[%s] TX TxFFE Lane %i Setting Request Done.', self.name[-1], Lane)         
         Gen4TxFFEReg = {'Lane':Lane, 'StartTx':True, 'SetNewReq':False, 'ClrNewReq':False, 'ReqPreset':0, 'SetReqDone':True, 'ClrReqDone':False, 'PresetSet':PresetRequested}
         self.Gen4TxFFE_fifo.put(Gen4TxFFEReg)
         
         yield self.NewRequestClr[Lane]
         self.NewRequestClr[Lane] = self.mtv.env.event()
         
         logger.debug('LSX[%s] TX TxFFE Lane %i Got New Request cleared.', self.name[-1], Lane)
         logger.debug('LSX[%s] TX TxFFE Clearing Request Done to Lane %i.', self.name[-1], Lane)
         Gen4TxFFEReg = {'Lane':Lane, 'StartTx':True, 'SetNewReq':False, 'ClrNewReq':False, 'ReqPreset':0, 'SetReqDone':False, 'ClrReqDone':True, 'PresetSet':PresetRequested}
         self.Gen4TxFFE_fifo.put(Gen4TxFFEReg)
      
      logger.debug('LSX[%s] TX TxFFE Lane %i Finished TxFFE', self.name[-1], Lane)
      if (Lane == 0):
         self.L0_Tx_TxFFE_Done.succeed()
      else:
         self.L1_Tx_TxFFE_Done.succeed()

      
      
   def ParseReg12(self, SBRegSpace):
      BinData = hex2bin(SBRegSpace[12].value).zfill(24)
      logger.debug('LSX[%s] Value of Register 12 is %s, and in binary it is %s', self.name[-1], SBRegSpace[12].value, BinData)
      Capabilities = {
         'L0En'         : (BinData[-9] == '1'),
         'L1En'         : (BinData[-10] == '1'),
         'Gen3'         : (BinData[-14] == '1'),
         'RS-FEC_G2'    : (BinData[-15] == '1'),
         'RS-FEC_G3'    : (BinData[-16] == '1'),
         'USB4SB'       : (BinData[-17] == '1'),
         'TBT3_Compat'  : (BinData[-18] == '1'),
         'Gen4'         : (BinData[-19] == '1'),
         'Asym_3TX_Sup' : (BinData[-20] == '1'),
         'Asym_3RX_Sup' : (BinData[-21] == '1'),
         'Asym_3TX_Req' : (BinData[-22] == '1'),
         'Asym_3RX_Req' : (BinData[-23] == '1')
      }
      return Capabilities
         
         
      
   def CapabilitieNegotiation(self, SelfCapabilities, LinkPartnerCapabilities):
      
      if (SelfCapabilities['Gen4'] & LinkPartnerCapabilities['Gen4']):
         self.LinkType['Gen'] = 4
      elif (SelfCapabilities['Gen3'] & LinkPartnerCapabilities['Gen3']):
         self.LinkType['Gen'] = 3
      else:
         self.LinkType['Gen'] = 2
      
      if (SelfCapabilities['Asym_3TX_Req'] & LinkPartnerCapabilities['Asym_3RX_Req']):
         self.LinkType['Asym3Tx'] = True
      
      if (SelfCapabilities['Asym_3RX_Req'] & LinkPartnerCapabilities['Asym_3TX_Req']):
         self.LinkType['Asym3Rx'] = True
      
      if (SelfCapabilities['L0En'] & LinkPartnerCapabilities['L0En']):
         self.LinkType['L0En'] = True
      else:
         self.LinkType['L0En'] = False
      
      if (SelfCapabilities['L1En'] & LinkPartnerCapabilities['L1En']):
         self.LinkType['L1En'] = True
      else:
         self.LinkType['L1En'] = False
         
      if (SelfCapabilities['USB4SB'] & LinkPartnerCapabilities['USB4SB']):
         self.LinkType['Sideband'] = 'USB4'
      else:
         self.LinkType['Sideband'] = 'TBT3'
         self.LinkType['Link'] = 'TBT3'
      
      if (self.LinkType['Gen'] == 4):
         self.LinkType['RS_FEC'] = True
      elif (self.LinkType['Gen'] == 3) & (SelfCapabilities['RS-FEC_G3'] & LinkPartnerCapabilities['RS-FEC_G3']):
         self.LinkType['RS_FEC'] = True
      elif (self.LinkType['Gen'] == 2) & (SelfCapabilities['RS-FEC_G2'] & LinkPartnerCapabilities['RS-FEC_G2']):
         self.LinkType['RS_FEC'] = True
      else:
         self.LinkType['RS_FEC'] = False
      
      if (self.LinkType['Gen'] == 4):
         self.LinkType['SSCAO'] = False
      else:
         self.LinkType['SSCAO'] = True

      USB4SB = int(self.LinkType['Sideband'] == 'USB4')
      TBT3Speed = int(self.LinkType['Link'] == 'TBT3')
      SSCAO = int(self.LinkType['SSCAO'])
      En3Tx = int(self.LinkType['Asym3Tx'])
      En3Rx = int(self.LinkType['Asym3Rx'])
      L0En = int(self.LinkType['L0En'])
      L1En = int(self.LinkType['L1En'])
      RSFEC = int(self.LinkType['RS_FEC'])
      Gen = (int(self.LinkType['Gen'] == 4) << 2) | (int(self.LinkType['Gen'] == 3) << 1) | (int(self.LinkType['Gen'] == 2))

      self.LaneParams = USB4SB | (RSFEC << 2) | (SSCAO << 3) | (TBT3Speed << 4) | (Gen << 12) | (En3Tx << 11) | (En3Rx << 10) | (L1En << 9) | (L0En << 8)
      

   def ConfigWr(self, Address=0, Data=0):
      self.from_test.put(mmi_msg({
          'cmd'      : 'RegifWrite',
          'addr'     : format_mmi_dn_address(opcode=XTOR_OPCODE.CONFIG_WRITE,addr=Address),
          'burst'    : 1,                 
          'data'     : [Data]
      }))


   def ConfigRd(self, Address=0):
      self.from_test.put(mmi_msg({
          'cmd'      : 'RegifWrite',
          'addr'     : format_mmi_dn_address(addr=Address, opcode=XTOR_OPCODE.CONFIG_READ),
          'burst'    : 1
      }))
   

   def WrImm(self, Address=0, Data=0):
      self.from_test.put(mmi_msg({
          'cmd'      : 'RegifWrite',
          'addr'     : format_mmi_dn_address(opcode=XTOR_OPCODE.CONFIG_WRITE, addr=Address, immediate=True),
          'burst'    : 1,                 
          'data'     : Data
      }))
   

   def RdImm(self, Address=0):
       self.from_test.put(mmi_msg({
           'cmd'      : 'RegifRead',
           'addr'     : format_mmi_dn_address(addr=Address, read=True),
           'burst'    : 1
       }))

   def DelayRltv_time(self, RltvTime=1000):
      self.from_test.put(mmi_msg({
          'cmd'      : 'RegifWrite',
          'addr'     : format_mmi_dn_address(seq=True, opcode=XTOR_OPCODE.WAIT_RELATIVE_TIME, addr=0, immediate=True),
          'burst'    : 1,                 
          'data'     : RltvTime
      }))
      
   def Ctrl0Wr(self, LSXEn=1, cnct=25,discnct=100,ibg=10,clkoffset=0,slower=0, setSBTX=0, clrSBTX=0):
      self.ConfigWr(Address=0x1, Data=format_lsx_ctrl0(LSXEn,cnct,discnct,ibg,clkoffset,slower,setSBTX,clrSBTX))


   def Ctrl1Wr(self, clkmult=100):
      self.ConfigWr(Address=0x2, Data=clkmult)


   def TxLtTrans(self, Symbol='LT_Fall', Lane=0,Error=0):
      self.ConfigWr(Address=0xF, Data=format_lt(Symbol, Lane, Error))


   def TxEltTrans(self, Type='ELT_OpDone', Error=0):
      self.ConfigWr(Address=0xF, Data=format_elt(Type, Error))


   def TxAtRdCmd(self, Reg=0xC, Len=4, CRC=0):
      if (self.AT_Txn_IP == 1):
         raise ValueError("An AT Read Command was sent before an AT Response was received.")
      self.AT_Txn_IP = 1
      self.Got_AT_Resp = self.mtv.env.event()
      CalculatedCRC = calculate_crc16_int(0x05 | (Reg << 8) | (Len << 16))
      CRC2Put = CalculatedCRC ^ CRC
      FirstDW = Reg | (Len << 8) | (CRC2Put << 16)
       
      self.ConfigWr(Address=0x10, Data=FirstDW)
               
      TransReg = 0x20050004 #AT Transaction, STX of AT Command and length of 4 (Reg, Len, 2 CRC)
               
      self.ConfigWr(Address=0xF, Data=TransReg)
       

   def TxAtWrCmd(self, Reg=0xD, Len=4, Data=0x00000000, CRC=0):
      if (self.AT_Txn_IP == 1):
         raise ValueError("An AT Write Command was sent before an AT Response was received.")
      self.AT_Txn_IP = 1
      # Updating Link Partner Register value
      self.PartnerSBRegSpace[Reg].WriteBytes(Data, Len)
      self.PartnerSBRegSpace[Reg].data_is_right = False
       
      self.Got_AT_Resp = self.mtv.env.event()
      CalculatedCRC = calculate_crc16_int(0x800005 | (Reg << 8) | (Len << 16) | (Data << 24))
      CRC2Put = CalculatedCRC ^ CRC
      FirstDW = Reg | (Len << 8) | (0x1 << 15) | ((Data & ((1 << 16) - 1)) << 16)
      Data = Data >> 16
      if Len == 1:
         NumOfDW = 2
         EndBit  = 24
         Address = 0x10
         FirstDW = FirstDW | ((CRC2Put & ((1 << 8) - 1)) << EndBit)
         Data2Wr = (CRC2Put >> 8) & ((1 << 8) - 1)
         self.ConfigWr(Address=0x10, Data=FirstDW)
         self.ConfigWr(Address=0x11, Data=Data2Wr)
      elif Len == 2:
         NumOfDW = 2
         Data2Wr = CRC2Put & ((1 << 16) - 1)
         EndBit  = 16
         Address = 0x10
         self.ConfigWr(Address=0x10, Data=FirstDW)
         self.ConfigWr(Address=0x11, Data=Data2Wr)
      else:
         self.ConfigWr(Address=0x10, Data=FirstDW)
         NumOfDW = ((Len - 2) // 4) + 1
         EndBit  = ((Len - 2) % 4) * 8
         for i in range(NumOfDW):
            Address = i + 0x11
            EndBit = min(32, (Len * 8) - 16 - (i * 32))
            if EndBit <= 16 :
               Data2Wr = Data | (CRC2Put << EndBit)
            elif EndBit == 32:   
               Data2Wr = Data & ((1 << 32) - 1)
               Data = Data >> 32
            elif EndBit == 24:
               Data2Wr = Data | ((CRC2Put & ((1 << 8) - 1))  << 24)

            self.ConfigWr(Address=Address, Data=Data2Wr)
      
         if EndBit  == 24:
            Address = Address + 1
            Data2Wr = (CRC2Put >> 8)
            self.ConfigWr(Address=Address, Data=Data2Wr)

      TransReg = 0x20000000
      TransReg = TransReg | (Len + 4)
      TransReg = TransReg | (0x5 << 16)
      
      self.ConfigWr(Address=0xF, Data=TransReg)
        

   def TxAtRdRsp(self, Reg=0xD, Len=4, Data=0x00000000, CRC=0):
       CalculatedCRC = calculate_crc16_int(0x04 | (Reg << 8) | (Len << 16) | (Data << 24))
       CRC2Put = CalculatedCRC ^ CRC
       FirstDW = Reg | (Len << 8) | ((Data & ((1 << 16) - 1)) << 16)
       Data = Data >> 16
       NumOfDW = ((Len-2) // 4) + 1
       EndBit = ((Len - 2) % 4) * 8

       self.ConfigWr(Address=0x10, Data=FirstDW)
       
       Address = 0x10 
       for i in range(NumOfDW):
          Address = i + 0x11
          EndBit = min(32, (Len * 8) - 16 - (i * 32))
          if EndBit <= 16 :
             Data2Wr = Data | (CRC2Put << EndBit)
          elif EndBit == 32:   
             Data2Wr = Data & ((1 << 32) - 1)
             Data = Data >> 32
          elif EndBit == 24:
             Data2Wr = Data | ((CRC2Put & ((1 << 8) - 1))  << 24)

          self.ConfigWr(Address=Address, Data=Data2Wr)
       
       if EndBit  == 24:
          Address = Address + 1
          Data2Wr = (CRC2Put >> 8)

          self.ConfigWr(Address=Address, Data=Data2Wr)

       TransReg = 0x20040000 #AT Transaction, STX of AT Response
       TransReg = TransReg | (Len + 4)
       
       self.ConfigWr(Address=0xF, Data=TransReg)
       


   def TxAtWrRsp(self, Reg=0xC, Len=4, Result=0, CRC=0):
       CalculatedCRC = calculate_crc16_int(0x04 | (Reg << 8) | (Len << 16))
       CRC2Put = CalculatedCRC ^ CRC
       FirstDW = Reg | (Len << 8) | (1 << 15) | (Result << 16) | ((CRC2Put & ((1 << 8) - 1)) << 24)

       self.ConfigWr(Address=0x10, Data=FirstDW)
       
       SecondDW = (CRC2Put >> 8)

       self.ConfigWr(Address=0x11, Data=SecondDW)

       TransReg = 0x20040005 #AT Transaction, STX of AT Response and length of 5 (Reg, Len, Result, 2 CRC)
               
       self.ConfigWr(Address=0xF, Data=TransReg)



   def TxRtRdCmd(self, Index=0, Reg=0xC, Len=4, CRC=0):
      if (self.RT_Txn_IP == 1):
         raise ValueError("An RT Read Command was sent before an RT Response was received.")
      logger.debug("LSX[%s] Transmit RT Read Command with Index %i, to Register %i", self.name[-1], Index, Reg)
      self.RT_Txn_IP = 1
      self.Got_RT_Resp = self.mtv.env.event()
      CalculatedCRC = calculate_crc16_int(0x41 | (Index << 1) | (Reg << 8) | (Len << 16))
      CRC2Put = CalculatedCRC ^ CRC
      FirstDW = Reg | (Len << 8) | (CRC2Put << 16)

      self.ConfigWr(Address=0x10, Data=FirstDW)
       
      TransReg = 0x10410004 | (Index << 17) #Addressed RT Command, STX of RT Command, Index and length of 4 (Reg, Len, 2 CRC)
               
      self.ConfigWr(Address=0xF, Data=TransReg)

       
   def TxRtWrCmd(self, Index=0, Reg=0xD, Len=4, Data=0x00000000, CRC=0):
      # Updating Link Partner Register value
      if (self.RT_Txn_IP == 1):
         raise ValueError("An RT Write Command was sent before an RT Response was received.")
      self.PartnerSBRegSpace[Reg].WriteBytes(Data, Len)
      self.PartnerSBRegSpace[Reg].data_is_right = False
      
      logger.debug("LSX[%s] Transmit RT Write Command with Index %i, to Register %i with Data %s", self.name[-1], Index, Reg, hex(Data))
      self.RT_Txn_IP = 1
      self.Got_RT_Resp = self.mtv.env.event()
      CalculatedCRC = calculate_crc16_int(0x800041 | (Index << 1) | (Reg << 8) | (Len << 16) | (Data << 24))
      CRC2Put = CalculatedCRC ^ CRC
      FirstDW = Reg | (Len << 8) | (0x1 << 15) | ((Data & ((1 << 16) - 1)) << 16)
      Data = Data >> 16
      NumOfDW = ((Len-2) // 4) + 1
      EndBit = ((Len - 2) % 4) * 8

      self.ConfigWr(Address=0x10, Data=FirstDW)

      for i in range(NumOfDW):
         Address = i + 0x11
         EndBit = min(32, (Len * 8) - 16 - (i * 32))
         if EndBit <= 16 :
            Data2Wr = Data | (CRC2Put << EndBit)
         elif EndBit == 32:   
            Data2Wr = Data & ((1 << 32) - 1)
            Data = Data >> 32
         elif EndBit == 24:
            Data2Wr = Data | ((CRC2Put & ((1 << 8) - 1))  << 24)
         self.ConfigWr(Address=Address, Data=Data2Wr)
       
      if EndBit  == 24:
         Address = Address + 1
         Data2Wr = (CRC2Put >> 8)

         self.ConfigWr(Address=Address, Data=Data2Wr)

      TransReg = 0x10410000 # Addressed RT Command STX
      TransReg = TransReg | (Len + 4) | (Index << 17)
       
      self.ConfigWr(Address=0xF, Data=TransReg)

         
   def TxRtRdRsp(self, Index=0, Reg=0xD, Len=4, Data=0x00000000, CRC=0):
      CalculatedCRC = calculate_crc16_int(0x40 | (Index << 1) | (Reg << 8) | (Len << 16) | (Data << 24))
      CRC2Put = CalculatedCRC ^ CRC
      FirstDW = Reg | (Len << 8) | ((Data & ((1 << 16) - 1)) << 16)
      Data = Data >> 16
      NumOfDW = ((Len-2) // 4) + 1
      EndBit = ((Len - 2) % 4) * 8

      self.ConfigWr(Address=0x10, Data=FirstDW)

      for i in range(NumOfDW):
         Address = i + 0x11
         EndBit = min(32, (Len * 8) - 16 - (i * 32))
         if EndBit <= 16 :
            Data2Wr = Data | (CRC2Put << EndBit)
         elif EndBit == 32:   
            Data2Wr = Data & ((1 << 32) - 1)
            Data = Data >> 32
         elif EndBit == 24:
            Data2Wr = Data | ((CRC2Put & ((1 << 8) - 1))  << 24)

         self.ConfigWr(Address=Address, Data=Data2Wr)
       
      if EndBit  == 24:
         Address = Address + 1
         Data2Wr = (CRC2Put >> 8)
          
         self.ConfigWr(Address=Address, Data=Data2Wr)

      TransReg = 0x10400000 #RT Transaction, STX of RT Response
      TransReg = TransReg | (Len + 4) | (Index << 17)
       
      self.ConfigWr(Address=0xF, Data=TransReg)
      logger.debug("LSX[%s] Transmit RT Read Response with Index %i, from Register %i, with Data %s", self.name[-1], Index, Reg, hex(Data))



   def TxRtWrRsp(self, Index=0, Reg=0xC, Len=4, Result=0, CRC=0):
      CalculatedCRC = calculate_crc16_int(0x800040 | (Index << 1) | (Reg << 8) | (Len << 16))
      CRC2Put = CalculatedCRC ^ CRC
      FirstDW = Reg | (Len << 8) | (1 << 15) | (Result << 16) | ((CRC2Put & ((1 << 8) - 1)) << 24)

      self.ConfigWr(Address=0x10, Data=FirstDW)
      
      SecondDW = (CRC2Put >> 8)

      self.ConfigWr(Address=0x11, Data=SecondDW)

      TransReg = 0x10400005 | (Index << 17) #RT Transaction, STX of RT Response and length of 5 (Reg, Len, Result, 2 CRC)
              
      self.ConfigWr(Address=0xF, Data=TransReg)



   def TxRtBcCmd(self, Index=0, CRC=0):


      CalculatedCRC = calculate_crc16_int(0x61 | (Index << 1) | (self.LaneParams << 8))
      CRC2Put = CalculatedCRC ^ CRC
      FirstDW = self.LaneParams | (CRC2Put << 16)

      self.ConfigWr(Address=0x10, Data=FirstDW)
      
      TransReg = 0x08610004 | (Index << 17) #Broadcast RT Command, STX of Broadcast RT Command, Index and length of 4 (2 Lane Parameters, 2 CRC)
              
      self.ConfigWr(Address=0xF, Data=TransReg)
      

   def ReceiveCmd(self, cmd):
      rx_header = hex(cmd['data'][0])[2:].zfill(8)
      stx_byte_h = rx_header[-2:]
      stx_byte_b = hex2bin(stx_byte_h)
      index = 0
      #logger.debug("Test: This is the STX Byte of the Command: %s", stx_byte_b)
      if (stx_byte_b[:2] == '00'):
         if (stx_byte_b[-6:] != '000101'):
            logger.debug("Test: ERROR in STX Byte of AT Command: %s", stx_byte_b)
            return 0
         else:
            TxnType = 'AT'
      elif (stx_byte_b[:2] == '01'):
         if (stx_byte_b[2] == '1'):
            logger.debug("Test: ERROR in STX Byte of RT Command: %s", stx_byte_b)
            return 0
         else:
            TxnType = 'RT'
            index = int(stx_byte_b[-6:-1], 2)
            #logger.debug("Test: Received RT Command with Index %i ", index)
      reg_h = rx_header[-4:-2]
      len_WnR_h = rx_header[-6:-4]
      len_WnR_b = hex2bin(len_WnR_h)
      len_d = int(len_WnR_b[-7:], 2)
      #logger.debug('Test: LSX received an %s Command with LEN and WnR byte %s', TxnType, len_WnR_b)                
      if (len_WnR_b[0] == '1'):
         logger.debug('Test: LSX[%s] received an %s Write Command to Register %s with Length of %i', self.name[-1], TxnType, reg_h, len_d)
         i = 1
         data2wr = ''
         while (i < (cmd['mlength'])):
            #logger.debug('Test: This is part %i out of %i parts', i+1, cmd['mlength'])
            if (i*8 <= len_d):
               #logger.debug('Test: Taking data %s and adding it to %s, getting %s', hex(cmd['data'][i])[2:].zfill(16), data2wr, (hex(cmd['data'][i])[2:].zfill(16) + data2wr))
               data2wr = hex(cmd['data'][i])[2:].zfill(16) + data2wr
            elif (i*8 > len_d): # if there is Data and CRC in a transaction
               data_bytes = len_d + 8 - 8*i
               #logger.debug('Test: data_bytes = %i', data_bytes)
               if (data_bytes == 0):
                  RxCRC = int(hex(cmd['data'][i])[2:].zfill(16)[-4:], 16)
                  #logger.debug('Test: The CRC is  %s', crc2check)
                  break
               #logger.debug('Test: Taking data %s and adding it to %s, getting %s', hex(cmd['data'][i])[2:].zfill(16)[-2*data_bytes:], data2wr, (hex(cmd['data'][i])[2:].zfill(16)[-2*data_bytes:] + data2wr))
               data2wr = hex(cmd['data'][i])[2:].zfill(16)[-2*data_bytes:] + data2wr
               if (data_bytes < 7):
                  RxCRC = int(hex(cmd['data'][i])[2:].zfill(16)[-(2*data_bytes+4):-2*data_bytes], 16)
                  #logger.debug('Test: Full data is %s, The CRC is  %s, break', hex(cmd['data'][i])[2:].zfill(16), crc2check)
                  break
               else:
                  RxCRC = int(hex(cmd['data'][i])[2:].zfill(16)[-(2*data_bytes+2):-2*data_bytes] + hex(cmd['data'][i+1])[2:].zfill(16)[-2:], 16)
                  #logger.debug('Test: The CRC is  %s, break', crc2check)
                  break
            i = i + 1
         data2check = data2wr + hex(cmd['data'][0])[2:].zfill(6)
         CalcCRC = calculate_crc16_int(int(data2check, 16))
         logger.debug("CRC Debug: This is the data for the calculated CRC: %s", data2check)
         logger.debug("CRC Debug: This is the value of the received CRC: %s", hex(RxCRC))
         logger.debug("CRC Debug: This is the value of the calculated CRC: %s", hex(CalcCRC))
         
         #writing the data to the register
         if (len_d > self.SBRegSpace[int(reg_h, 16)].size_in_bytes):
            logger.debug("Test: ERROR %s Write Command id too long for the destination register, Len is %i and size is %i", TxnType, len_d, self.SBRegSpace[int(reg_h, 16)].size_in_bytes)
            if (TxnType == 'AT'):
               self.TxAtWrRsp(Reg=int(reg_h, 16), Len=0, Result=1)
            else:
               self.TxRtWrRsp(Index=index, Reg=int(reg_h, 16), Len=0, Result=1)
         else:
            if (int(reg_h, 16) == 14):
               binaryData = bin(int(data2wr, 16))[2:].zfill(32)
               if (self.SBRegSpace[14].bit(StartTx) == 0) and (binaryData[-StartTx-1] == '1'):
                  self.StartTxSet[0].succeed()
               if (self.SBRegSpace[14].bit(StartTx+8) == 0) and (binaryData[-StartTx-1-8] == '1'):
                  self.StartTxSet[1].succeed()

               if (self.SBRegSpace[14].bit(NewReq) == 0) and (binaryData[-NewReq-1] == '1'):
                  self.NewRequestSet[0].succeed()
                  self.NewRequestSet[0] = self.mtv.env.event()
               elif (self.SBRegSpace[14].bit(NewReq) == 1) and (binaryData[-NewReq-1] == '0'):
                  self.NewRequestClr[0].succeed()
                  self.NewRequestClr[0] = self.mtv.env.event()
               if (self.SBRegSpace[14].bit(NewReq+8) == 0) and (binaryData[-NewReq-1-8] == '1'):
                  self.NewRequestSet[1].succeed()
                  self.NewRequestSet[1] = self.mtv.env.event()
               elif (self.SBRegSpace[14].bit(NewReq+8) == 1) and (binaryData[-NewReq-1-8] == '0'):
                  self.NewRequestClr[1].succeed()
                  self.NewRequestClr[1] = self.mtv.env.event()

               if (self.SBRegSpace[14].bit(ReqDone) == 0) and (binaryData[-ReqDone-1] == '1'):
                  self.RequestDoneSet[0].succeed()
                  self.RequestDoneSet[0] = self.mtv.env.event()
               elif (self.SBRegSpace[14].bit(ReqDone) == 1) and (binaryData[-ReqDone-1] == '0'):
                  self.RequestDoneClr[0].succeed()
                  self.RequestDoneClr[0] = self.mtv.env.event()
               if (self.SBRegSpace[14].bit(ReqDone+8) == 0) and (binaryData[-ReqDone-1-8] == '1'):
                  self.RequestDoneSet[1].succeed()
                  self.RequestDoneSet[1] = self.mtv.env.event()
               elif (self.SBRegSpace[14].bit(ReqDone+8) == 1) and (binaryData[-ReqDone-1-8] == '0'):
                  self.RequestDoneClr[1].succeed()
                  self.RequestDoneClr[1] = self.mtv.env.event()

            #logger.debug("Test: Register %i is with Length %i, Value before the write is %s, Value to write is %s, Value after the write is %s",int(reg_h, 16), len_d, self.SBRegSpace[int(reg_h, 16)].value, data2wr, self.SBRegSpace[int(reg_h, 16)].value[:-2*len_d] + data2wr)
            self.SBRegSpace[int(reg_h, 16)].value = self.SBRegSpace[int(reg_h, 16)].value[:-2*len_d] + data2wr
            if not self.LSXAnalyzer: 
               if (TxnType == 'AT'):
                  self.TxAtWrRsp(Reg=int(reg_h, 16), Len=self.SBRegSpace[int(reg_h, 16)].size_in_bytes, Result=0)
               else:
                  self.TxRtWrRsp(Index=index, Reg=int(reg_h, 16), Len=self.SBRegSpace[int(reg_h, 16)].size_in_bytes, Result=0)
      else:
         logger.debug('Test: LSX[%s] received an %s Read Command From Register %s with Length of %i', self.name[-1], TxnType, reg_h, len_d)
         if (len_d > self.SBRegSpace[int(reg_h, 16)].size_in_bytes):
            logger.debug('Test: Bytes to read %i is greater then register size %i. Will return only %i bytes.', len_d, self.SBRegSpace[int(reg_h, 16)].size_in_bytes, self.SBRegSpace[int(reg_h, 16)].size_in_bytes)
            len_d = self.SBRegSpace[int(reg_h, 16)].size_in_bytes
         data2check = hex(cmd['data'][0])[2:].zfill(6)
         #logger.debug('Test: CRC to check is %s', crc2check)
         CalcCRC = calculate_crc16_int(int(data2check, 16))
         RxCRC = int(hex(cmd['data'][1])[-4:], 16)
         logger.debug("CRC Debug: This is the data for the calculated CRC: %s", data2check)
         logger.debug("CRC Debug: This is the value of the calculated CRC: %s", hex(CalcCRC))
         logger.debug("CRC Debug: This is the value of the actual CRC: %s", hex(RxCRC))
         if (CalcCRC == RxCRC):
            #logger.debug('Test: Value of register %s is %s', reg_h, self.SBRegSpace[int(reg_h, 16)].value)
            FromReg = self.SBRegSpace[int(reg_h, 16)].value[-2*len_d:]
            #logger.debug('Test: First %i bytes from register %s is %s', len_d, reg_h, FromReg)
            if (TxnType == 'AT'):
               self.TxAtRdRsp(Reg=int(reg_h, 16), Len=len_d, Data=int(FromReg,16))
            else:
               self.TxRtRdRsp(Index=index, Reg=int(reg_h, 16), Len=len_d, Data=int(FromReg,16))
         else:
            logger.debug("Test: ERROR Bad CRC, still not implemented")

   def ReceiveRsp(self, rsp):
      rx_header = hex(rsp['data'][0])[2:].zfill(8)
      stx_byte_h = rx_header[-2:]
      stx_byte_b = hex2bin(stx_byte_h)
      index = 0
      #logger.debug("Test: This is the STX Byte of the Response: %s", stx_byte_b)
      if (stx_byte_b[:2] == '00'):
         TxnType = 'AT'
         if (stx_byte_b[-6:] != '000100'):
            #logger.debug("Test: ERROR in STX Byte of AT Command: %s", stx_byte_b)
            return 0
      elif (stx_byte_b[:2] == '01'):
         if (stx_byte_b[2] == '1'):
            #logger.debug("Test: ERROR in STX Byte of RT Command: %s", stx_byte_b)
            return 0
         else:
            TxnType = 'RT'
            index = int(stx_byte_b[-6:-1], 2)
            #logger.debug("Test: Received RT Command with Index %i ", index)
      reg_h = rx_header[-4:-2]
      len_WnR_h = rx_header[-6:-4]
      len_WnR_b = hex2bin(len_WnR_h)
      len_d = int(len_WnR_b[-7:], 2)
      #logger.debug('Test: LSX received an %s Response with LEN and WnR byte %s', TxnType, len_WnR_b)                
      if (len_WnR_b[0] == '1'):
         logger.debug('Test: LSX received an %s Write Response to Register 0x%s with Length of %i', TxnType, reg_h, len_d)
         if (len_d != self.PartnerSBRegSpace[int(reg_h, 16)].size_in_bytes):
            logger.debug('Test: The size of Register 0x%s is not %i but %i', reg_h, self.PartnerSBRegSpace[int(reg_h, 16)].size_in_bytes, len_d)
            self.PartnerSBRegSpace[int(reg_h, 16)].size_in_bytes = len_d
            self.PartnerSBRegSpace[int(reg_h, 16)].length_is_known = True
         if (rsp['mlength'] != 2):
            logger.debug('Test: ERROR : Length should be 2 but it is %i', rsp['mlength'])
         else:
            RxCRC      = int(hex(rsp['data'][1])[2:].zfill(16)[-6:-2], 16)
            result     = hex(rsp['data'][1])[2:].zfill(16)[-2:]
            data2check = result + len_WnR_h + reg_h + stx_byte_h
            #logger.debug('Test: CRC to check is %s and Result is %s', crc2check, result)
            CalcCRC = calculate_crc16_int(int(data2check, 16))
            
            logger.debug("CRC Debug: This is the data for the calculated CRC: %s", data2check)
            logger.debug("CRC Debug: This is the value of the calculated CRC: %s", hex(CalcCRC))
            logger.debug("CRC Debug: This is the value of the received CRC: %s", hex(RxCRC))
            if (True):
               self.PartnerSBRegSpace[int(reg_h, 16)].data_is_right = True
      else:
         logger.debug('Test: LSX received an %s Read Response From Register 0x%s with Length of %i', TxnType, reg_h, len_d)
         if (len_d > self.PartnerSBRegSpace[int(reg_h, 16)].size_in_bytes):
            logger.debug('Test: Bytes to read %i is greater then register size %i. Will return only %i bytes.', len_d, self.PartnerSBRegSpace[int(reg_h, 16)].size_in_bytes, self.PartnerSBRegSpace[int(reg_h, 16)].size_in_bytes)
            len_d = self.PartnerSBRegSpace[int(reg_h, 16)].size_in_bytes
         i = 1
         ReadData = ''
         while (i < (rsp['mlength'])):
            #logger.debug('Test: This is part %i out of %i parts', i+1, rsp['mlength'])
            if (i*8 <= len_d):
               #logger.debug('Test: Taking data %s and adding it to %s, getting %s', hex(rsp['data'][i])[2:].zfill(16), ReadData, (hex(rsp['data'][i])[2:].zfill(16) + ReadData))
               ReadData = hex(rsp['data'][i])[2:].zfill(16) + ReadData
            elif (i*8 > len_d): # if there is Data and CRC in a transaction
               data_bytes = len_d + 8 - 8*i
               #logger.debug('Test: data_bytes = %i', data_bytes)
               if (data_bytes == 0):
                  RxCRC = int(hex(rsp['data'][i])[-4:], 16)
                  #logger.debug('Test: The CRC is  %s, break', crc2check)
                  break
               #logger.debug('Test: Taking data %s and adding it to %s, getting %s', hex(rsp['data'][i])[2:].zfill(16)[-2*data_bytes:], ReadData, (hex(rsp['data'][i])[2:].zfill(16)[-2*data_bytes:] + ReadData))
               ReadData = hex(rsp['data'][i])[2:].zfill(16)[-2*data_bytes:] + ReadData
               if (data_bytes < 7):
                  RxCRC = int(hex(rsp['data'][i])[2:].zfill(16)[-(2*data_bytes+4):-2*data_bytes], 16)
                  #logger.debug('Test: The CRC is  %s, break', crc2check)
                  break
               else:
                  RxCRC = int(hex(rsp['data'][i])[2:].zfill(16)[-(2*data_bytes+2):-2*data_bytes] + hex(rsp['data'][i+1])[2:].zfill(16)[-2:], 16)
                  #logger.debug('Test: The CRC is  %s, break', crc2check)
                  break
            i = i + 1
         data2check = ReadData + hex(rsp['data'][0])[2:].zfill(6)
         CalcCRC = calculate_crc16_int(int(data2check, 16))
         logger.debug("CRC Debug: This is the data for the calculated CRC: %s", data2check)
         logger.debug("CRC Debug: This is the value of the calculated CRC: %s", hex(CalcCRC))
         logger.debug("CRC Debug: This is the value of the received CRC: %s", hex(RxCRC))
         if (True):
            if (int(reg_h, 16) == 13):
               binaryData = bin(int(ReadData, 16))[2:].zfill(32)
               if (self.PartnerSBRegSpace[13].bit(TxActive) == 0) and (binaryData[-TxActive-1] == '1'):
                  self.TxActiveSet[0].succeed()
               if (self.PartnerSBRegSpace[13].bit(TxActive+8) == 0) and (binaryData[-TxActive-1-8] == '1'):
                  self.TxActiveSet[1].succeed()
                  
               if (self.PartnerSBRegSpace[13].bit(NewReq) == 0) and (binaryData[-NewReq-1] == '1'):
                  self.NewRequestSet[0].succeed()
                  self.NewRequestSet[0] = self.mtv.env.event()
               elif (self.PartnerSBRegSpace[13].bit(NewReq) == 1) and (binaryData[-NewReq-1] == '0'):
                  self.NewRequestClr[0].succeed()
                  self.NewRequestClr[0] = self.mtv.env.event()
               if (self.PartnerSBRegSpace[13].bit(NewReq+8) == 0) and (binaryData[-NewReq-1-8] == '1'):
                  self.NewRequestSet[1].succeed()
                  self.NewRequestSet[1] = self.mtv.env.event()
               elif (self.PartnerSBRegSpace[13].bit(NewReq+8) == 1) and (binaryData[-NewReq-1-8] == '0'):
                  self.NewRequestClr[1].succeed()
                  self.NewRequestClr[1] = self.mtv.env.event()
                  
               if (self.PartnerSBRegSpace[13].bit(ReqDone) == 0) and (binaryData[-ReqDone-1] == '1'):
                  self.RequestDoneSet[0].succeed()
                  self.RequestDoneSet[0] = self.mtv.env.event()
               elif (self.PartnerSBRegSpace[13].bit(ReqDone) == 1) and (binaryData[-ReqDone-1] == '0'):
                  self.RequestDoneClr[0].succeed()
                  self.RequestDoneClr[0] = self.mtv.env.event()
               if (self.PartnerSBRegSpace[13].bit(ReqDone+8) == 0) and (binaryData[-ReqDone-1-8] == '1'):
                  self.RequestDoneSet[1].succeed()
                  self.RequestDoneSet[1] = self.mtv.env.event()
               elif (self.PartnerSBRegSpace[13].bit(ReqDone+8) == 1) and (binaryData[-ReqDone-1-8] == '0'):
                  self.RequestDoneClr[1].succeed()
                  self.RequestDoneClr[1] = self.mtv.env.event()

               if (self.PartnerSBRegSpace[13].bit(RxLocked) == 0) and (binaryData[-RxLocked-1] == '1'):
                  self.RxLocked[0].succeed()
               if (self.PartnerSBRegSpace[13].bit(RxLocked+8) == 0) and (binaryData[-RxLocked-1-8] == '1'):
                  self.RxLocked[1].succeed()

               
            self.PartnerSBRegSpace[int(reg_h, 16)].value = ReadData
            self.PartnerSBRegSpace[int(reg_h, 16)].data_is_right = True

      if TxnType == 'AT':
         logger.debug("Got AT Response!")
         self.Got_AT_Resp.succeed()
         if (len_WnR_b[0] == 0):
            self.Got_AT_RD_Resp.succeed()
         else:
            self.Got_AT_WR_Resp.succeed()
         self.AT_Txn_IP = 0
         self.Got_AT_Resp = self.mtv.env.event()
         self.Got_AT_RD_Resp = self.mtv.env.event()
         self.Got_AT_WR_Resp = self.mtv.env.event()
      if TxnType == 'RT':
         logger.debug("Got RT Response!")
         self.Got_RT_Resp.succeed()
         self.RT_Txn_IP = 0


   def ReceiveFwLog(self, resp):
      self.fw_log.append(resp['data'])
      logger.debug("FW LOG: Added this to the log: %s", hex(resp['data']))
      logger.debug("FW LOG: There are %i log entries", len(self.fw_log))
      
      
      
   def ReceiveBc(self, cmd):
      self.Got_BC_RT = self.mtv.env.event()
      rx_header = hex(cmd['data'][0])[2:].zfill(8)
      stx_byte_h = rx_header[-2:]
      stx_byte_b = hex2bin(stx_byte_h)
      index = 0
      #logger.debug("Test: This is the STX Byte of the Command: %s", stx_byte_b)
      if (stx_byte_b[:2] == '00'):
         logger.debug("Test: ERROR in STX Byte of AT Command: %s", stx_byte_b)
         return 0
      elif (stx_byte_b[:2] == '01'):
         if (stx_byte_b[2] != '1') | (stx_byte_b[-1] != '1'):
            logger.debug("Test: ERROR in STX Byte of BC RT Command: %s", stx_byte_b)
            return 0
         else:
            TxnType = 'RT'
            index = int(stx_byte_b[-5:-1], 2)
            LaneParams = hex(cmd['data'][0]).zfill(16)[-6:-2]
            logger.debug('Test: LSX received an BC RT Command with Index %i and Lane Params %s', index, LaneParams)
            self.Got_BC_RT.succeed()
            return int(LaneParams, 16)



def hex2bin(hex_value):
   bin_value = bin(int(hex_value, 16))[2:].zfill(len(hex_value) * 4)
   return bin_value

def FlipBit(hex_value, bit_pos):
   bin_value = bin(int(hex_value, 16))[2:].zfill(len(hex_value) * 4)
   calc_bit_pos = len(bin_value) - bit_pos - 1
   if (bin_value[calc_bit_pos] == '1'):
      new_bit_value = '0'
   else:
      new_bit_value = '1'
   new_bin_value = bin_value[:calc_bit_pos] + new_bit_value + bin_value[calc_bit_pos+1:]
   new_hex_value = hex(int(new_bin_value, 2))[2:]
   return new_hex_value
   
   

def calculate_crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, byteorder='little')


def calculate_crc16_int(hex_integer):
    try:
        data_bytes = hex_integer.to_bytes((hex_integer.bit_length() + 7) // 8, byteorder='little')
        crc_result = calculate_crc16(data_bytes)[-1:] + calculate_crc16(data_bytes)[:1]
        return int(crc_result.hex().upper(), 16)
    except ValueError:
        print("Invalid hex integer input.")
        return None


def format_lsx_ctrl0(LSXEn=0,cnct=0,discnct=0,ibg=0,clkoffset=0,slower=0,setSBTX=0,clrSBTX=0):
    CNCT_LSB      =  2
    DISCNCT_LSB   =  8
    IBG_LSB       =  18
    CLKOFFSET_LSB =  24
    SLOWER_LSB    =  30
    LSXEN_LSB     =  31

    data = 0x0               #rdata_vld12 64 bit
    data = data | setSBTX
    data = data | (clrSBTX << 1)
    data = data | (cnct << CNCT_LSB)
    data = data | (discnct << DISCNCT_LSB)
    data = data | (ibg << IBG_LSB)
    data = data | (clkoffset << CLKOFFSET_LSB)
    data = data | (slower << SLOWER_LSB)
    data = data | (LSXEn << LSXEN_LSB)
    return data


def format_lt(Symbol='LT_Fall', Lane=0,Error=0):
    SYM_LSB       =  0
    LANE_LSB      =  5

    symbol_mapping = {
        'LT_Fall'    : 0x0,
        'LT_Resume'  : 0x2,
        'LT_LRoff'   : 0x3,
        'LT_Switch'  : 0x4,
        'LT_Ack'     : 0x7
    }
    
    lse = 0x80
    lse = lse | symbol_mapping[Symbol]
    lse = lse | (Lane << LANE_LSB)
    data = lse | (((~lse ^ Error) & 0xFF) << 8)  | 0x80000000
          
    return data

def format_elt(Type='ELT_OpDone', Error=0):
    TYPE_LSB     =  4

    type_mapping = {
        'ELT_OpDone': 0x0,
        'ELT_Recovery': 0x2
    }
    
    lse = 0x88
    lse = lse | (type_mapping[Type] << TYPE_LSB)
    if Error == 0:
       data = lse | ((~lse & 0xFF) << 8)  | 0x40000000
    else:
       data = lse | ((Error & 0xFF) << 8) | 0x40000000
          
    return data
