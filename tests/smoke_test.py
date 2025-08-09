import os
import sys

# Ensure repository root is on sys.path when running this file directly
THIS_DIR = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from ternuino_designer.core.logic import Circuit, SwitchTernary, TNOR, TAND, TNOT, Transistor, TLatch, Probe


def run():
    c = Circuit()
    sw1 = SwitchTernary('sw1', 1)
    sw2 = SwitchTernary('sw2', -1)
    and1 = TAND('and1')
    nor1 = TNOR('nor1')
    t1 = Transistor('t1')
    l1 = TLatch('l1')
    p1 = Probe('p1')

    for comp in [sw1, sw2, and1, nor1, t1, l1, p1]:
        c.add(comp)

    # wire similar to sample
    c.connect('sw1', 'out', 'and1', 'in1')
    c.connect('sw2', 'out', 'and1', 'in2')

    c.connect('and1', 'out', 't1', 'presence')
    c.connect('sw1', 'out', 't1', 'sign')

    c.connect('t1', 'out', 'nor1', 'in1')
    c.connect('sw2', 'out', 'nor1', 'in2')

    c.connect('nor1', 'out', 'l1', 'in')
    c.connect('sw1', 'out', 'l1', 'enable')
    c.connect('l1', 'out', 'p1', 'in')

    # initial step
    c.step()
    print('Probe after step 1:', c.get_probe('p1'))

    # Toggle and step again
    sw1.toggle()
    sw2.toggle()
    c.step()
    print('Probe after step 2:', c.get_probe('p1'))


if __name__ == '__main__':
    run()
