from types import SimpleNamespace

import pytest

from crash_analyzer.dwarf import Member, Structure, SymbolFile, TypeContext
from crash_analyzer.renderers import VmBranchSelector


def die(tag, *, target=None, children=(), **attributes):
    if target is not None:
        attributes["DW_AT_type"] = 1
    return SimpleNamespace(
        tag=tag,
        attributes={name: SimpleNamespace(value=value) for name, value in attributes.items()},
        iter_children=lambda: iter(children),
        get_DIE_from_attribute=lambda name: target,
    )


@pytest.fixture
def symbols():
    symbols = object.__new__(SymbolFile)
    symbols.pointer_size = 8
    symbols.byteorder = "little"
    symbols._renderers = []
    symbols._selectors = []
    return symbols


def array(element, *counts):
    return die(
        "DW_TAG_array_type",
        target=element,
        children=[die("DW_TAG_subrange_type", DW_AT_upper_bound=count - 1) for count in counts],
    )


def layout(symbols, array_type):
    size = symbols._size(array_type)
    return Structure(
        "container",
        "struct container",
        "struct",
        size,
        None,
        [Member("items", array_type, 0, size)],
        symbols,
    )


def test_pointer_array_size_and_sparse_elements(symbols):
    pointer = die("DW_TAG_pointer_type", target=die("DW_TAG_pointer_type"))
    pointers = array(pointer, 4)
    assert symbols._size(pointers) == 32
    data = dict(enumerate((0xFFFF8487075B1000).to_bytes(8, "little")))
    data.update(enumerate(bytes(8), start=16))
    data[24] = 1
    observed = layout(symbols, pointers).observed_values(data)
    assert [(value.path, value.offset, value.value) for value in observed] == [
        ("items[0]", 0, "0xffff8487075b1000"),
        ("items[2]", 16, "NULL"),
        ("items[3]", 24, None),
    ]
    assert all(value.size == 8 for value in observed)


def test_last_element_alone_is_observed(symbols):
    pointers = array(die("DW_TAG_pointer_type"), 4)
    data = dict(enumerate((0x1234).to_bytes(8, "little"), start=24))
    observed = layout(symbols, pointers).observed_values(data)
    assert [(value.path, value.value) for value in observed] == [
        ("items[3]", "0x0000000000001234"),
    ]


@pytest.mark.parametrize("byteorder", ["little", "big"])
def test_multidimensional_scalar_array(symbols, byteorder):
    symbols.byteorder = byteorder
    integer = die("DW_TAG_base_type", DW_AT_byte_size=4, DW_AT_encoding=5)
    integers = array(integer, 2, 3)
    raw = b"".join(value.to_bytes(4, byteorder, signed=True) for value in (1, -2, 3, 4, 5, 6))
    assert symbols._size(integers) == 24
    assert symbols.decode(integers, raw) == "[[1, -2, 3], [4, 5, 6]]"
    observed = layout(symbols, integers).observed_values(dict(enumerate(raw)))
    assert [value.path for value in observed] == [
        "items[0][0]",
        "items[0][1]",
        "items[0][2]",
        "items[1][0]",
        "items[1][1]",
        "items[1][2]",
    ]
    assert [value.value for value in observed] == ["1", "-2", "3", "4", "5", "6"]


def test_complete_array_member_is_rendered_inline(symbols):
    pointers = array(die("DW_TAG_pointer_type"), 2)
    raw = (0x1234).to_bytes(8, "little") + bytes(8)
    container = layout(symbols, pointers)
    assert container.value_for(container.members[0], dict(enumerate(raw))) == (
        "[0x0000000000001234, NULL]"
    )


def test_count_metadata_and_unknown_bounds(symbols):
    pointer = die("DW_TAG_pointer_type")
    counted = die(
        "DW_TAG_array_type", target=pointer, children=[die("DW_TAG_subrange_type", DW_AT_count=4)]
    )
    assert symbols._size(counted) == 32
    assert symbols.type_name(counted) == "<unknown> *[4]"
    unknown = die("DW_TAG_array_type", target=pointer, children=[die("DW_TAG_subrange_type")])
    assert symbols._size(unknown) is None
    assert symbols._size(array(pointer, 0)) == 0


@pytest.mark.parametrize(
    "branches, context, active",
    [
        (("pv", "hvm"), TypeContext(vm_type="hvm"), "hvm"),
        (("vmx", "svm"), TypeContext(hvm_backend="vmx"), "vmx"),
        (("nvmx", "nsvm"), TypeContext(nested_virt=False, hvm_backend="vmx"), None),
    ],
)
def test_all_branches_expands_arrays_in_filtered_union(symbols, branches, context, active):
    symbols._selectors = [VmBranchSelector()]
    pointers = array(die("DW_TAG_pointer_type"), 2)
    union = die(
        "DW_TAG_union_type",
        DW_AT_byte_size=16,
        children=[die("DW_TAG_member", target=pointers, DW_AT_name=name) for name in branches],
    )
    container = layout(symbols, union)
    data = dict(enumerate((0x1234).to_bytes(8, "little") + bytes(8)))
    selected = container.observed_values(data, context)
    if active is None:
        assert not any(f"items.{name}" in value.path for name in branches for value in selected)
    else:
        assert [value.path for value in selected] == [f"items.{active}[0]", f"items.{active}[1]"]
    expanded = container.observed_values(data, context, all_branches=True)
    assert [value.path for value in expanded] == [
        f"items.{name}[{index}]" for name in branches for index in range(2)
    ]
    assert [value.value for value in expanded] == ["0x0000000000001234", "NULL"] * 2
