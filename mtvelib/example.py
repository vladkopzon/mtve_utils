#!/usr/bin/env python3

from pkt_wr import *

if __name__ == "__main__":
    #ID-1
    id = [1]
    data = [101, 201, 301, 401]
    wr_data = id + data 
    pkt_wr(wr_data)
    #ID-2
    id = [2]
    data = [101, 201, 301, 401]
    wr_data = id + data 
    pkt_wr(wr_data)

