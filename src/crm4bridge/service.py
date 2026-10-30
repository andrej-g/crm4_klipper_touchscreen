"""Optional systemd notification, without a python-systemd dependency."""
import os
import socket


def notify_ready():
    address = os.environ.get('NOTIFY_SOCKET')
    if not address:
        return
    if address.startswith('@'):
        address = '\0' + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
        channel.connect(address)
        channel.sendall(b'READY=1\nSTATUS=Screen answered; bridge running')
