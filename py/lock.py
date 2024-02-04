#!/usr/bin/env python3

import fcntl
import os

def test_lock(filename):
    with open(filename, 'w') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print("File locking is supported.")
        except IOError:
            print("File locking is not supported.")

        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

if __name__ == "__main__":
    test_lock('testfile')  # Replace with your file path

#rbr
