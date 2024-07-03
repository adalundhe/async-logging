from enum import Enum


class NodeType(Enum):
    WORKER = "WORKER"
    PROVISIONER = "PROVISIONER"
    GATE = "GATE"
