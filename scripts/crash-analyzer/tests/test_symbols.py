from pathlib import Path

import pytest

from crash_analyzer.dump import load_dump
from crash_analyzer.dwarf import ANONYMOUS, SymbolFile, TypeContext

SYMBOLS = Path(__file__).parents[3] / "xen-syms-4.17.6-12"


class CustomSpinlockRenderer:
    def matches(self, symbols: object, type_die: object) -> bool:
        return True

    def render(self, symbols: object, type_die: object, data: bytes) -> str:
        return "custom spinlock renderer"


@pytest.mark.skipif(not SYMBOLS.exists(), reason="sample Xen symbol file is not checked out")
def test_sample_xen_types() -> None:
    with SymbolFile(SYMBOLS) as symbols:
        domain = symbols.structure("struct domain")
        shared_info = symbols.structure("shared_info_t")
        vcpu = symbols.structure("struct vcpu")

        assert domain.size == 4096
        assert [(member.name, member.offset) for member in domain.members[:4]] == [
            ("domain_id", 0),
            ("max_vcpus", 4),
            ("vcpu", 8),
            ("shared_info", 16),
        ]
        assert shared_info.size == 3136
        assert shared_info.kind == "union"
        assert [(member.name, member.offset) for member in shared_info.members] == [
            ("native", 0),
            ("compat", 0),
        ]
        shared_dump = load_dump(SYMBOLS.parents[0] / "dom0.structures.log")[1]
        observed = shared_info.observed_values(shared_dump.bytes)
        assert observed[0].path == "native.vcpu_info[0].evtchn_upcall_pending"
        assert observed[0].value == "0"

        domain_lock = next(member for member in domain.members if member.name == "domain_lock")
        assert domain_lock.offset is not None
        lock_bytes = bytes.fromhex("51 00 51 00 ff 0f 00 00")
        lock_data = {domain_lock.offset + index: value for index, value in enumerate(lock_bytes)}
        lock_value = domain.observed_values(lock_data)[0]
        assert lock_value.path == "domain_lock"
        assert lock_value.value == (
            "FREE (tickets head=81, tail=81; recursive owner=none; depth=0)"
        )

        options = next(member for member in domain.members if member.name == "options")
        arch = next(member for member in domain.members if member.name == "arch")
        assert options.offset is not None
        assert arch.offset is not None
        union_offset = arch.offset + 32
        pv_data = {
            options.offset + index: value
            for index, value in enumerate((0).to_bytes(options.size or 4, "little"))
        }
        pv_data.update({union_offset + index: index + 1 for index in range(8)})
        pv_paths = {value.path for value in domain.observed_values(pv_data)}
        assert domain.vm_type(pv_data) == "pv"
        assert f"arch.{ANONYMOUS}.pv.gdt_ldt_l1tab" in pv_paths
        assert not any(".hvm." in path for path in pv_paths)

        hvm_data = {
            options.offset + index: value
            for index, value in enumerate((1).to_bytes(options.size or 4, "little"))
        }
        hvm_data.update({union_offset + index: index + 1 for index in range(24)})
        hvm_paths = {value.path for value in domain.observed_values(hvm_data)}
        assert domain.vm_type(hvm_data) == "hvm"
        assert f"arch.{ANONYMOUS}.hvm.ioreq_gfn.base" in hvm_paths
        assert not any(".pv." in path for path in hvm_paths)

        # Resolve real constant tables from the ELF, including Xen's writable
        # .rodata section, rather than relying on union-value heuristics.
        csw_tables = {
            symbols.hvm_backend(symbol["st_value"]): symbol["st_value"]
            for symbol in symbols._elf.get_section_by_name(".symtab").iter_symbols()
            if symbol.name.startswith("csw.")
        }
        arch_layout = symbols.structure("struct arch_domain")
        csw_member = next(member for member in arch_layout.members if member.name == "ctxt_switch")
        assert csw_member.offset is not None
        for backend in ("vmx", "svm"):
            backend_data = dict(hvm_data)
            backend_data.update(
                {
                    arch.offset + csw_member.offset + index: value
                    for index, value in enumerate(
                        csw_tables[backend].to_bytes(symbols.pointer_size, symbols.byteorder)
                    )
                }
            )
            assert domain.context(backend_data) == TypeContext(
                vm_type="hvm", nested_virt=False, hvm_backend=backend
            )

        arch_data = {640 + 384 + 448 + index: value for index, value in enumerate(range(8))}
        arch_data.update(
            {640 + 384 + 936 + 56 + index: value for index, value in enumerate(range(8))}
        )
        vmx_paths = {
            value.path
            for value in vcpu.observed_values(
                arch_data, TypeContext(vm_type="hvm", nested_virt=True)
            )
        }
        assert f"arch.{ANONYMOUS}.hvm.{ANONYMOUS}.vmx.vmcs_pa" in vmx_paths
        assert f"arch.{ANONYMOUS}.hvm.nvcpu.u.nvmx.vmxon_region_pa" in vmx_paths
        assert f"arch.{ANONYMOUS}.hvm.{ANONYMOUS}.svm.vmcb" in vmx_paths
        assert f"arch.{ANONYMOUS}.hvm.nvcpu.u.nsvm.ns_gif" in vmx_paths

        no_nested_paths = {
            value.path
            for value in vcpu.observed_values(
                arch_data, TypeContext(vm_type="hvm", nested_virt=False)
            )
        }
        assert not any(".nvmx." in path or ".nsvm." in path for path in no_nested_paths)
        assert vcpu.size == 3136


@pytest.mark.skipif(not SYMBOLS.exists(), reason="sample Xen symbol file is not checked out")
def test_custom_renderer_precedes_builtins() -> None:
    with SymbolFile(SYMBOLS, renderers=[CustomSpinlockRenderer()]) as symbols:
        domain = symbols.structure("struct domain")
        domain_lock = next(member for member in domain.members if member.name == "domain_lock")
        assert domain_lock.offset is not None
        lock_data = {
            domain_lock.offset + index: value
            for index, value in enumerate(bytes.fromhex("51 00 51 00 ff 0f 00 00"))
        }
        assert domain.observed_values(lock_data)[0].value == "custom spinlock renderer"
