# crash-analyzer

`crash-analyzer` explores Xen structure dumps using the DWARF type information
embedded in a Xen `xen-syms` ELF file. It understands the sparse form of the
diagnostic output: regions represented by `...` remain unavailable instead of
being treated as zero-filled memory.

Pass the matching Xen symbol file first, followed by one or more dump files:

```console
uv run crash-analyzer xen-syms-4.17.6-12 dom0.structures.log
uv run crash-analyzer xen-syms-4.17.6-12 dom0.structures.log dom5413.structures.log
uv run crash-analyzer xen-syms-4.17.6-12 *.structures.log --all
```

The ELF/DWARF index and structure layouts are reused across the batch. Runtime
domain and vCPU context is resolved separately for each dump file. Each input
produces a separate output in the same directory: `dom5413.structures.log`
becomes `dom5413.parsed.log`, or `dom5413.parsed.json` with `--json`. Other input
names use their stem followed by `.parsed.log` or `.parsed.json`. The command
prints the input-to-output paths; JSON records include a `source` path. Files are
processed in argument order. A failed file is reported on stderr while the
remaining files continue; any failure makes the command exit with status 2.
Existing outputs are replaced only after a file finishes successfully.

Full human-readable logs are written by default. Use `--json` explicitly for
machine-readable output. The analyzer follows
captured nested structure and array elements, while still leaving omitted bytes
unavailable. The symbol file must contain DWARF debug information; a stripped
Xen binary or a plain `nm` output file is not sufficient for structure layouts.
Scalar and pointer arrays are expanded into indexed entries such as
`evtchn_group[0]`; partially captured elements show `<unavailable>` and wholly
omitted elements are skipped. Arrays and nested fields are expanded in both
output modes. `--all` only bypasses context-based member selection, showing all
union branches, including PV/HVM, VMX/SVM, and nested NVMX/NSVM variants.
For `struct domain`, the active `arch` PV/HVM union branch is selected from the
DWARF-resolved `options` field and Xen's fixed public HVM domain flag. If the
abridged dump does not contain `options`, the branch cannot be selected and is
left unresolved. A `struct vcpu` inherits this information when its captured
`domain` pointer refers to a dumped domain.
The VMX/SVM backend is resolved from the domain's captured `arch.ctxt_switch`
pointer. The analyzer reads the constant table from the matching ELF file and
checks its three function pointers against the VMX/SVM function symbols. The
backend selects the VMX/SVM and nested NVMX/NSVM union branches and is included
as `hvm_backend` in JSON output. Missing bytes, symbols, or an address that does
not match the ELF leave both branches visible. A `struct vcpu` inherits the
backend from its dumped domain. The nested union is hidden when the domain's
nested-virtualization flag is clear.
Known Xen `spinlock_t` values are summarized as one line with lock state, ticket
head/tail, recursive owner, and recursion depth. Use `pahole` for full type
layouts.

Special value formatting is implemented as registered renderers. The Python API
accepts custom `renderers` and context-sensitive `selectors` in `SymbolFile`, so
types such as `spinlock_t`, `struct arch_domain`, and future Xen-specific types
can be handled without changing the generic DWARF walker.

From this repository, run the project commands from `scripts/crash-analyzer`,
or pass that directory to `uv` with `--project`.
