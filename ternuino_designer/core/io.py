from __future__ import annotations
from typing import Dict, Any
import json
from .logic import Circuit, COMPONENT_REGISTRY


def load_circuit_from_json(text: str) -> Circuit:
    data = json.loads(text)
    c = Circuit()

    # Create components
    for comp in data.get('components', []):
        cid = comp['id']
        ctype = comp['type']
        params = comp.get('params', {})
        cls = COMPONENT_REGISTRY.get(ctype)
        if cls is None:
            raise ValueError(f"Unknown component type: {ctype}")
        # Instantiate with id and optional params
        if params:
            obj = cls(cid, **params)
        else:
            obj = cls(cid)
        c.add(obj)

    # Create wires
    for w in data.get('wires', []):
        f = w['from']
        t = w['to']
        c.connect(f['componentId'], f['port'], t['componentId'], t['port'])

    return c


def dump_circuit_to_json(c: Circuit) -> str:
    # Minimal export (positions not tracked in core)
    comps = []
    for comp in c.components.values():
        entry = {
            'id': comp.id,
            'type': comp.type,
            'params': {}
        }
        # serialize switch value
        if comp.type == 'SwitchBinary':
            entry['params'] = {'value': comp.ports['out'].value}
        elif comp.type == 'SwitchTernary':
            entry['params'] = {'value': comp.ports['out'].value}
        comps.append(entry)

    wires = []
    for w in c.wires:
        wires.append({
            'from': {'componentId': w.src_comp, 'port': w.src_port},
            'to': {'componentId': w.dst_comp, 'port': w.dst_port},
        })

    data = {'name': 'Exported', 'version': 1, 'components': comps, 'wires': wires}
    return json.dumps(data, indent=2)
