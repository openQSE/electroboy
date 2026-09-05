from .base import Transport


class TcpTransport(Transport):
    def send(self, value: str) -> str:
        return f"tcp:{value}"
