from .base import Transport


class MemoryTransport(Transport):
    def send(self, value: str) -> str:
        return value
