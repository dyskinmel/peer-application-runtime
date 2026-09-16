#!/usr/bin/env python3
"""Single public fixture transcript over an inherited socket, not a PAR peer."""
import os,socket,sys,time
fd=int(sys.argv[1]);mode=sys.argv[2]
with socket.socket(fileno=fd) as s:
    first=s.recv(1)
    if first!=b'P':raise SystemExit(3)
    if mode=='eof':raise SystemExit(0)
    if mode=='stall':
        s.sendall(b'S')
        while s.recv(1):pass
    else:s.sendall(b'OK' if mode=='ok' else b'NO')
