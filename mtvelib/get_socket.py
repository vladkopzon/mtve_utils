#!/usr/bin/env python3
import argparse
import socket

def get_free_port(host='localhost', port=0):
    # Create a socket object.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
    except socket.error as e:
        print("Error binding socket: {}".format(e))
        return

    # Try to listen for connections on the socket.
    s.listen()
    return port
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-port' , type=int,  default=0)
    parser.add_argument('-host',  type=str,  default='localhost')

    args = parser.parse_args()
    port = get_free_port(host=args.host, port=args.port)
    if port:
        print ("(%s, %d) is free!" % (args.host, args.port))
    else:
        print ("(%s, %d) is busy!" % (args.host, args.port))
        
