import datetime

import msgspec

from .log_level import LogLevel
from .node_type import NodeType


class Entry(msgspec.Struct):
    level: LogLevel
    node_type: NodeType
    node_id: int
    line_number: int
    epoch: int
    sequence: int
    filename: str
    function_name: str
    event: str
    context: str
    thread_id: int
    timestamp: datetime.datetime
    tags: set[str] = set()
    test: str | None = None
    workflow: str | None = None
    hook: str | None = None
    location: str = "local"

    def to_message(self):
        test_source = ""
        if self.test and self.workflow:
            test_source = f"{self.test}.{self.workflow} - "

        if self.test and self.workflow and self.hook:
            test_source = f"{test_source}.{self.workflow}.{self.hook} - "

        return f"{self.timestamp} - {self.level} - {self.node_id} / {self.thread_id} - {test_source}{self.event}: {self.context}\n".encode()

    def to_error_string(self):
        test_source = ""
        if self.test and self.workflow:
            test_source = f"{self.test}.{self.workflow} - "

        if self.test and self.workflow and self.hook:
            test_source = f"{test_source}.{self.workflow}.{self.hook} - "

        return f"{self.timestamp} - {self.level} - {self.node_id} / {self.thread_id} - {self.filename}:{self.function_name}.{self.line_number} - {test_source}{self.event}: {self.context}\n"
