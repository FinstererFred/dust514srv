# Python 2.7 -- runs inside the DUST 514 client.
# Forwards everything that goes through the logging module to the dev server as UDP datagrams,
# so we can read the client's Python log even though the release build discards it.
import logging
import socket
import sys

DEFAULT_ADDR = ('127.0.0.1', 8514)
CHUNK = 1200


class UdpForwardHandler(logging.Handler):

    def __init__(self, addr):
        logging.Handler.__init__(self)
        self.addr = addr
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def emit(self, record):
        try:
            msg = self.format(record)
            if isinstance(msg, unicode):
                msg = msg.encode('utf-8', 'replace')
            line = '%s %s %s' % (record.levelname, record.name, msg)
            for i in range(0, len(line), CHUNK):
                self.sock.sendto(line[i:i + CHUNK], self.addr)
        except Exception:
            pass


def Install(addr=DEFAULT_ADDR, level=logging.DEBUG):
    handler = UdpForwardHandler(addr)
    handler.setFormatter(logging.Formatter('%(message)s'))
    handler.setLevel(level)
    logging.root.addHandler(handler)
    logging.root.setLevel(level)
    logging.getLogger('dustlogfwd').info('log forwarding active, sys.path=%r', sys.path)
    return handler
