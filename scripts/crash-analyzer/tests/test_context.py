from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from crash_analyzer.dwarf import Member, Structure, SymbolFile, TypeContext
from crash_analyzer.renderers import VmBranchSelector


@pytest.fixture
def symbols():
    symbols = object.__new__(SymbolFile)
    symbols.pointer_size = 8
    symbols.byteorder = "little"
    symbols._csw_backends = {}
    symbols._csw_functions = None
    functions = {
        f"{backend}_{name}": 0x2000 + backend_index * 0x100 + index * 0x10
        for backend_index, backend in enumerate(("vmx", "svm"))
        for index, name in enumerate(("ctxt_switch_from", "ctxt_switch_to", "do_resume"))
    }
    elf_symbols = []
    for name, address in functions.items():
        symbol = Mock()
        symbol.name = name
        symbol.__getitem__ = Mock(
            side_effect={
                "st_value": address,
                "st_info": {"type": "STT_FUNC"},
                "st_shndx": 1,
            }.__getitem__
        )
        elf_symbols.append(symbol)
    raw = b"".join(address.to_bytes(8, "little") for address in functions.values())
    section = Mock()
    section.name = ".data"
    section.__getitem__ = Mock(
        side_effect={
            "sh_addr": 0x1000,
            "sh_size": len(raw),
            "sh_type": "SHT_PROGBITS",
            "sh_flags": 2,
        }.__getitem__
    )
    section.data.return_value = raw
    symbols._elf = Mock()
    symbols._elf.iter_sections.return_value = [section]
    symbols._elf.get_section_by_name.return_value.iter_symbols.return_value = elf_symbols
    members = [
        Member(name, None, index * 8, 8) for index, name in enumerate(("from", "to", "tail"))
    ]
    symbols.structure = Mock(return_value=SimpleNamespace(size=24, members=members))
    return symbols


@pytest.mark.parametrize(
    "address, expected",
    [(0x1000, "vmx"), (0x1018, "svm"), (0, None), (0x1008, None), (0x1020, None), (0x9999, None)],
)
def test_backend_requires_complete_matching_table(symbols, address, expected):
    assert symbols.hvm_backend(address) == expected


def test_missing_symbols_leave_backend_unknown(symbols):
    symbols._elf.get_section_by_name.return_value = None
    assert symbols.hvm_backend(0x1000) is None


def test_xen_rodata_can_have_writable_elf_flag(symbols):
    section = symbols._elf.iter_sections.return_value[0]
    section.name = ".rodata"
    original = section.__getitem__.side_effect
    section.__getitem__.side_effect = lambda key: 3 if key == "sh_flags" else original(key)
    assert symbols.hvm_backend(0x1000) == "vmx"


@pytest.mark.parametrize(
    "flags, section_type", [(3, "SHT_PROGBITS"), (0, "SHT_PROGBITS"), (2, "SHT_NOBITS")]
)
def test_mutable_or_unavailable_table_leaves_backend_unknown(symbols, flags, section_type):
    section = symbols._elf.iter_sections.return_value[0]
    section.__getitem__ = Mock(
        side_effect={
            "sh_addr": 0x1000,
            "sh_size": 48,
            "sh_type": section_type,
            "sh_flags": flags,
        }.__getitem__
    )
    assert symbols.hvm_backend(0x1000) is None


def test_domain_resolves_backend_even_without_options(symbols):
    child = SimpleNamespace(
        tag="DW_TAG_member",
        attributes={
            "DW_AT_name": SimpleNamespace(value=b"ctxt_switch"),
            "DW_AT_data_member_location": SimpleNamespace(value=16),
        },
    )
    arch_die = SimpleNamespace(tag="DW_TAG_structure_type", iter_children=lambda: [child])
    domain = Structure(
        "domain",
        "struct domain",
        "struct",
        64,
        None,
        [Member("options", None, 0, 4), Member("arch", arch_die, 8, 40)],
        symbols,
    )
    data = dict(enumerate((0x1000).to_bytes(8, "little"), start=24))
    assert domain.context(data) == TypeContext(hvm_backend="vmx")
    data.update(enumerate((65).to_bytes(4, "little")))
    assert domain.context(data) == TypeContext(vm_type="hvm", nested_virt=True, hvm_backend="vmx")
    del data[24]
    assert domain.context(data) == TypeContext(vm_type="hvm", nested_virt=True)


@pytest.mark.parametrize("backend", ["vmx", "svm", None])
@pytest.mark.parametrize("nested", [True, False, None])
def test_backend_selects_normal_and_nested_union(backend, nested):
    def member(name):
        return SimpleNamespace(attributes={"DW_AT_name": SimpleNamespace(value=name)})

    selector = VmBranchSelector()
    context = TypeContext(vm_type="hvm", nested_virt=nested, hvm_backend=backend)
    normal_members = [member("vmx"), member("svm")]
    selected = selector.select(None, None, normal_members, context)
    assert selected == (None if backend is None else [normal_members[backend == "svm"]])
    nested_members = [member("nvmx"), member("nsvm")]
    selected = selector.select(None, None, nested_members, context)
    expected = None if backend is None else [nested_members[backend == "svm"]]
    assert selected == ([] if nested is False else expected)
