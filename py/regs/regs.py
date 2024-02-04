#!/usr/bin/env python3

import sys
import os
import hjson
import re
import logging
import csv

from typing import NamedTuple
from types import MethodType

class RegNameSpec(NamedTuple):
    name:           str
    domain:         str = ''
    sub_function:   str = ''
    rtl_name:       str = ''


class registers(object):

    MAIN_REG_FIELDS_2_EXTRACT = [
        ['Domain','domain'],
        ['Sub-function','sub_function'],
        ['pcie_sw_regs_access_23_23','b23'],
        ['cio_sw_regs_access_22_22','b22'],
        ['tar_cs_20_19','cs'],
        ['tar_port_18_13','port'],
        ['VSEC_name-tar_index_12_0','offset'],
        ['Offset-HEX','offset-hex'],
        ['RTL Name', 'rtl_name'],
        ['VSEC_name-tar_index_12_0', 'index'],
    ]

    REG_FIELDS_2_EXTRACT = [
        ['Field Name','name'],
        ['MSB','msb'],
        ['LSB','lsb'],
        ['Default value','value'],
        ['Attribute','type'],
        ['RTL Name', 'rtl_name'],
    ]

    PARSER = {'name': 'Register Name'}
    
    def __init__(self, csv_file=None):
        self.csv_file = os.path.abspath(csv_file)
        self.RDB = {
            'regs':{},
            'multi_inst': {},
        }
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        

    def convert_numeric(self, value):
        try:
            if value.startswith('0x'):
                return int(value, 16)  # Convert hexadecimal to int
            else:
                return int(value)  # Convert string to int
        except ValueError:
            return value
    

    def parse(self):
        with open(self.csv_file, 'r') as file:
            reader = csv.DictReader(file)
            dicts = list(reader)
        for d in dicts:
            name = d[self.PARSER['name']]
            field = {}
            if name:
                if self.RDB['regs'].get(name):
                    if self.RDB['multi_inst'].get(name):
                        self.RDB['multi_inst'][name] += self.RDB['regs'][name]
                    else:
                        self.RDB['multi_inst'][name] = [self.RDB['regs'][name]]
                reg = {}
                fields = {}
                reg_name = name
                reg[name] = {}
                reg[name]['fields'] = []
                for elm in self.MAIN_REG_FIELDS_2_EXTRACT:
                    reg[name][elm[1]] = self.convert_numeric(d[elm[0]])
                for elm in self.REG_FIELDS_2_EXTRACT:
                    field[elm[1]] = self.convert_numeric(d[elm[0]])
            else:
                for elm in self.REG_FIELDS_2_EXTRACT:
                    field[elm[1]] = self.convert_numeric(d[elm[0]])
            reg[reg_name]['fields'] += [field]
            self.RDB['regs'][reg_name] = reg


    def find(self, args:RegNameSpec):
        reg = None
        if self.RDB['regs'].get(args.name):
            if self.RDB['multi_inst'].get(args.name):
                if args.sub_function:
                    for inst in self.RDB['multi_inst'][args.name] + [self.RDB['regs'][args.name]]:
                        if inst[args.name]['sub_function'] == args.sub_function:
                            reg = inst[args.name]
                            reg['uniq_name'] = args.name + '.' + args.sub_function
                else:
                    self.logger.critical(f"[WRS] Wrong Register Spec for multi instance reg {args.name}")
            else:
                reg = self.RDB['regs'][args.name][args.name]
                reg['uniq_name'] = args.name
        else:
            self.logger.critical(f"[NER] Non existant register: {args.name}") 
            raise KeyError(f"Failed to find register {args.name}")
            
        return self.bless(reg)
        #return reg

    
    
    def get_addr(self, args:RegNameSpec):
        reg = self.find(args)
        reg_addr = (reg['cs'] << 19 ) | ( reg['port'] << 13) | reg['index']
        return reg_addr
    
        
    def parse_data(self, args:RegNameSpec, value=0):
        reg = self.find(args)
        
        result = {}
        for field in reg['fields']:
            msb = field['msb']
            lsb = field['lsb']
            fvalue = (value >> lsb) & ((1 << (msb - lsb + 1)) - 1)
            result[field['name']] = hex(fvalue)
        return result

    
    def bless(self, reg):
        attributes = {}

        class __reg():
            def __init__(self):
                self.__reg__ = reg
                self.name    = reg['uniq_name']
                self.cs      = reg['cs']
                self.port    = reg['port']
                self.index   = reg['index']
                
            def __str__(self):
                return repr(self.__dict__)

            def get_value(self):
                return self.set_value()
            
            def set_value(self, value=None):
                #TBD: check overflow
                if not value:
                    got_value = False
                    value     = 0
                else:
                    got_value = True

                for field in self.__reg__['fields']:
                    msb = field['msb']
                    lsb = field['lsb']
                    if got_value:
                        fvalue = (value >> lsb) & ((1 << (msb - lsb + 1)) - 1)
                        field['value'] = fvalue
                    else:
                        value |= field['value'] << lsb
                return value

            def get_addr(self):
                reg_addr = (self.cs << 19 ) | ( self.port << 13) | self.index
                return reg_addr
 
                        
        class __field:
            def __init__(self, name, field):
                self.name    = name
                self.field   = field
                self.__reg__ = reg

            def __str__(self):
                return repr(self.__dict__)

            def get_value(self):
                return self.field['value']
            
            def set_value(self, value):
                #TBD: check overflow
                self.field['value'] = value
                return value

        for field in reg['fields']:
            attributes[field['name']] = __field(name=field['name'], field=field)

        blessed_reg = type(reg['uniq_name'], (__reg,), attributes)
        inst = blessed_reg()
        return inst


################################################################################    
    
if __name__ == "__main__":
    import argparse
    logging.basicConfig(format='%(levelname)s - %(module)s.%(funcName)s - %(message)s')
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument('-csv_file', type=str, required=True,
                        help='Specify AllRegs.csv file')
    parser.add_argument('-dev' ,  action='store_true',
                        help='For script development only')

    args = parser.parse_args()

    R = registers(csv_file=args.csv_file)
    R.parse()

    # for reg, rdb in R.RDB['regs'].items():
    #     print(rdb)

    reg = R.find(RegNameSpec(name='DFT_PROCMON'))
    print(reg)
    print(reg.name)
    print(reg.tap_prc_mon_sel_out.name)
    print(hex(reg.tap_prc_mon_sel.get_value()))
    print(hex(reg.tap_prc_mon_sel.set_value(0x33)))
    print(hex(reg.tap_prc_mon_sel.get_value()))
    print(hex(reg.set_value(0xAAAAAAAA)))
    print(hex(reg.get_value()))
    print(reg.get_addr())
    print(f'cs={reg.cs}, port={reg.port}, index={reg.index}')

    
