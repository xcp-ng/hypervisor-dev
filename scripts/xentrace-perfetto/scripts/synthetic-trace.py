"""Write a tiny synthetic xentrace file to stdout (2 pCPUs, HVM exits, C-states,
hypercalls, a cross-CPU wakeup and lost records) for testing without a Xen host.

    python3 scripts/synthetic-trace.py > synth.bin
    xentrace-perfetto --cpu-mhz 2000 synth.bin synth.pftrace
"""
import struct, sys
MHZ = 2000
def rec(ev, tsc, *d):
    hdr = ev | (len(d) << 28) | ((1 << 31) if tsc is not None else 0)
    out = struct.pack('<I', hdr)
    if tsc is not None: out += struct.pack('<Q', tsc)
    return out + b''.join(struct.pack('<I', x & 0xffffffff) for x in d)
def us(x): return x * MHZ  # microseconds -> TSC
def rs(t, dom, vcpu, old, new): return rec(0x00021001 | old << 8 | new << 4, us(t), dom << 16 | vcpu, 0)
R, RB, B = 0, 1, 2
IDLE = 0x7fff
def window(cpu, recs):
    body = b''.join(recs)
    return struct.pack('<IiI', 0x0001f003 | 2 << 28, cpu, len(body)) + body
cpu0 = [
    rs(1000, IDLE, 0, R, RB), rs(1000, 1, 0, RB, R),
    rec(0x00081002, us(1100), 48, 0xffff1000),
    rec(0x00082001, us(1150), 0x1234, 0x4),            # pf_xen
    rec(0x00081001, us(1200)),
    rec(0x00081102, us(1300), 30, 0x1000, 0xffffffff), # VMX_EXIT64, IO_INSTRUCTION
    rec(0x00082216, us(1310), 0x80, 1, 0xab),           # ioport_write
    rec(0x00081001, us(1400)),
    rec(0x00081002, us(1500), 12, 0x2000),             # HLT, descheduled before VMENTRY
    rs(1550, 1, 0, R, B), rs(1550, IDLE, 0, RB, R),
    rec(0x00801002, us(1600), 2, 0, 0, 0),             # C2 entry
    rec(0x00801003, us(1900), 2, 0, 0, 0),
    rs(2000, IDLE, 0, R, RB), rs(2000, 0, 0, RB, R),
    rec(0x0020100d, us(2100), 29 | 1 << 20 | 2 << 22, 7, 0x89abcdef, 0x01234567),
    rec(0x00028004, None, 0x00010000),                 # sched_wake, no TSC
    rs(2200, 0, 0, R, B), rs(2200, IDLE, 0, RB, R),
]
cpu1 = [
    rs(900, IDLE, 1, R, RB), rs(900, 1, 1, RB, R),
    rec(0x00801001, us(950), 2000000, 3000000),         # freq change
    rec(0x00081002, us(1000), 1, 0x3000),                # EXTERNAL_INTERRUPT
    rec(0x00081001, us(1050)),
    rs(1800, 1, 0, B, RB),                               # wake of d1v0, logged on CPU1
    rec(0x0001f001, us(1850), 5, 1 << 16 | 1, us(1840) & 0xffffffff, us(1840) >> 32),
    rec(0x00081002, us(2500), 0x99, 0x3000),             # unknown reason
    rec(0x00081001, us(2600)),
]
cpu0b = [rs(2300, IDLE, 0, R, RB), rs(2300, 1, 0, RB, R), rec(0x00081002, us(2400), 10, 0x5000), rec(0x00081001, us(2410))]
sys.stdout.buffer.write(window(0, cpu0) + window(1, cpu1) + window(0, cpu0b))
