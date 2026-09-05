class Record:
    def serialize(self) -> str:
        raise NotImplementedError


class UserRecord(Record):
    def __init__(self, name: str) -> None:
        self.name = name

    def serialize(self) -> str:
        return self.name
