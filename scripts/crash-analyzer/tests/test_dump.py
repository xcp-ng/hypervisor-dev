from io import StringIO

from crash_analyzer.dump import parse_dump


def test_parse_sparse_dump() -> None:
    dumps = parse_dump(
        StringIO(
            """Xen structures for Domain 0

struct domain (0xffff831012ba3000)
0000: 00 00 00 00 10 00 00 00  b0 33 bb 12 10 83 ff ff  0x0000001000000000 0xffff831012bb33b0
...

struct vcpu (0xffff831012b94000) for vcpu 0
0000: 00 00 00 00 13 00 00 00  00 71 1a f9 08 83 ff ff  0x0000001300000000 0xffff8308f91a7100
..."""
        )
    )

    assert len(dumps) == 2
    assert dumps[0].declared_type == "struct domain"
    assert dumps[0].address == 0xFFFF831012BA3000
    assert dumps[0].read(0, 16) == bytes.fromhex("00 00 00 00 10 00 00 00 b0 33 bb 12 10 83 ff ff")
    assert dumps[0].read(16, 1) is None
    assert dumps[1].vcpu == 0
