from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# Ternary values: -1, 0, 1
TValue = int  # constrained to {-1, 0, 1}


def clamp_t(v: int) -> TValue:
    if v > 1:
        return 1
    if v < -1:
        return -1
    return v


def resolve_wire(drivers: List[TValue]) -> TValue:
    """Resolve multiple drivers on a wire.
    - if both -1 and 1 present, return 0 (conflict => null)
    - else return the unique non-zero if any, else 0
    """
    s = set(drivers)
    if -1 in s and 1 in s:
        return 0
    for val in (1, -1):
        if val in s:
            return val
    return 0


@dataclass
class Port:
    id: str
    direction: str  # 'in' or 'out'
    value: TValue = 0


@dataclass
class Component:
    id: str
    type: str
    ports: Dict[str, Port] = field(default_factory=dict)

    def get_in(self, name: str) -> TValue:
        return self.ports[name].value

    def set_out(self, name: str, val: TValue) -> None:
        self.ports[name].value = clamp_t(val)

    def step(self) -> None:
        pass


class SwitchBinary(Component):
    def __init__(self, id: str, value: int = 0):
        super().__init__(id, 'SwitchBinary', {
            'out': Port('out', 'out', 0)
        })
        self.value = 1 if value else 0
        self.set_out('out', self.value)

    def toggle(self):
        self.value = 0 if self.value == 1 else 1
        self.set_out('out', self.value)


class SwitchTernary(Component):
    def __init__(self, id: str, value: int = 0):
        super().__init__(id, 'SwitchTernary', {
            'out': Port('out', 'out', 0)
        })
        self.value = clamp_t(value)
        self.set_out('out', self.value)

    def toggle(self):
        # cycle -1 -> 0 -> 1 -> -1
        order = [-1, 0, 1]
        idx = (order.index(self.value) + 1) % 3
        self.value = order[idx]
        self.set_out('out', self.value)


class TNOT(Component):
    def __init__(self, id: str):
        super().__init__(id, 'TNOT', {
            'in': Port('in', 'in', 0),
            'out': Port('out', 'out', 0),
        })

    def step(self) -> None:
        x = self.get_in('in')
        self.set_out('out', -x)


class TAND(Component):
    def __init__(self, id: str):
        super().__init__(id, 'TAND', {
            'in1': Port('in1', 'in', 0),
            'in2': Port('in2', 'in', 0),
            'out': Port('out', 'out', 0),
        })

    def step(self) -> None:
        a = self.get_in('in1')
        b = self.get_in('in2')
        self.set_out('out', min(a, b))


class TNOR(Component):
    def __init__(self, id: str):
        super().__init__(id, 'TNOR', {
            'in1': Port('in1', 'in', 0),
            'in2': Port('in2', 'in', 0),
            'out': Port('out', 'out', 0),
        })

    def step(self) -> None:
        a = self.get_in('in1')
        b = self.get_in('in2')
        self.set_out('out', -max(a, b))


class Transistor(Component):
    """Ternary transistor with two inputs:
    - presence: non-zero enables conduction
    - sign: the sign/value to pass if enabled
    Output is sign when enabled, else 0.
    """
    def __init__(self, id: str):
        super().__init__(id, 'Transistor', {
            'presence': Port('presence', 'in', 0),
            'sign': Port('sign', 'in', 0),
            'out': Port('out', 'out', 0),
        })

    def step(self) -> None:
        p = self.get_in('presence')
        s = self.get_in('sign')
        if p != 0 and s != 0:
            self.set_out('out', s)
        else:
            self.set_out('out', 0)


class TLatch(Component):
    """Transparent latch with enable:
    - when enable == 1: store input value
    - else: hold
    """
    def __init__(self, id: str):
        super().__init__(id, 'TLatch', {
            'in': Port('in', 'in', 0),
            'enable': Port('enable', 'in', 0),
            'out': Port('out', 'out', 0),
        })
        self._state: TValue = 0

    def step(self) -> None:
        if self.get_in('enable') == 1:
            self._state = self.get_in('in')
        self.set_out('out', self._state)


class Probe(Component):
    def __init__(self, id: str):
        super().__init__(id, 'Probe', {
            'in': Port('in', 'in', 0)
        })
        self.last: TValue = 0

    def step(self) -> None:
        self.last = self.get_in('in')


class TFullAdder(Component):
    """Balanced ternary full adder cell.
    Ports:
    - ai, bi, ci (in): input trits in {-1,0,1}
    - so (out): sum trit in {-1,0,1}
    - co (out): carry trit in {-1,0,1}
    Implements: a + b + c = so + 3*co
    """
    def __init__(self, id: str):
        super().__init__(id, 'TFullAdder', {
            'ai': Port('ai', 'in', 0),
            'bi': Port('bi', 'in', 0),
            'ci': Port('ci', 'in', 0),
            'so': Port('so', 'out', 0),
            'co': Port('co', 'out', 0),
        })

    def step(self) -> None:
        a = self.get_in('ai')
        b = self.get_in('bi')
        c = self.get_in('ci')
        total = a + b + c  # in [-3..3]
        # nearest integer carry in {-1,0,1}
        co = int(round(total / 3.0))
        if co > 1:
            co = 1
        elif co < -1:
            co = -1
        so = total - 3 * co
        # clamp for safety
        self.set_out('co', clamp_t(co))
        self.set_out('so', clamp_t(so))


@dataclass
class Wire:
    src_comp: str
    src_port: str
    dst_comp: str
    dst_port: str


class Circuit:
    def __init__(self):
        self.components: Dict[str, Component] = {}
        self.wires: List[Wire] = []

    def add(self, comp: Component):
        if comp.id in self.components:
            raise ValueError(f"Duplicate component id {comp.id}")
        self.components[comp.id] = comp

    def connect(self, src_comp: str, src_port: str, dst_comp: str, dst_port: str):
        self.wires.append(Wire(src_comp, src_port, dst_comp, dst_port))

    def step(self):
        # 1) Collect drivers for each input port
        inputs: Dict[Tuple[str, str], List[TValue]] = {}
        for w in self.wires:
            src = self.components[w.src_comp]
            val = src.ports[w.src_port].value
            key = (w.dst_comp, w.dst_port)
            inputs.setdefault(key, []).append(val)

        # 2) Resolve and write into input ports
        for (comp_id, port_name), drivers in inputs.items():
            comp = self.components[comp_id]
            comp.ports[port_name].value = resolve_wire(drivers)

        # 3) Step all components (which update outputs)
        for comp in self.components.values():
            comp.step()

    def set_switch(self, comp_id: str, value: int):
        c = self.components[comp_id]
        if isinstance(c, SwitchBinary):
            c.value = 1 if value != 0 else 0
            c.set_out('out', c.value)
        elif isinstance(c, SwitchTernary):
            c.value = clamp_t(value)
            c.set_out('out', c.value)
        else:
            raise ValueError("Component is not a switch")

    def get_probe(self, comp_id: str) -> TValue:
        c = self.components[comp_id]
        if not isinstance(c, Probe):
            raise ValueError("Component is not a probe")
        return c.last


COMPONENT_REGISTRY = {
    'SwitchBinary': SwitchBinary,
    'SwitchTernary': SwitchTernary,
    'TNOT': TNOT,
    'TAND': TAND,
    'TNOR': TNOR,
    'Transistor': Transistor,
    'TLatch': TLatch,
    'Probe': Probe,
    'TFullAdder': TFullAdder,
}
