from .memory import MemoryTransport
from .tcp import TcpTransport

TRANSPORTS = {
    "memory": MemoryTransport,
    "tcp": TcpTransport,
}


def create_transport(name: str):
    return TRANSPORTS[name]()
