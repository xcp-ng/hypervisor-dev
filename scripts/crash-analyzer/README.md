# crash-analyzer

`crash-analyzer` explores Xen structure dumps using the DWARF type information
embedded in a Xen `xen-syms` ELF file. It understands the sparse form of the
diagnostic output: regions represented by `...` remain unavailable instead of
being treated as zero-filled memory.

The project provides an inspection command:

```console
uv run crash-analyzer inspect dom0.structures.log xen-syms-4.17.6-12
uv run crash-analyzer inspect dom0.structures.log xen-syms-4.17.6-12 --all
```

Use `--json` with `inspect` for machine-readable output. `inspect` follows
captured nested structure and array elements, while still leaving omitted bytes
unavailable. The symbol file must contain DWARF debug information; a stripped
Xen binary or a plain `nm` output file is not sufficient for structure layouts.
For `struct domain`, the active `arch` PV/HVM union branch is selected from the
DWARF-resolved `options` field and Xen's fixed public HVM domain flag. If the
abridged dump does not contain `options`, the branch cannot be selected and is
left unresolved. A `struct vcpu` inherits this information when its captured
`domain` pointer refers to a dumped domain.
The VMX/SVM union has no discriminator field in Xen's structures, so both
branches remain separately labeled. The nested NVMX/NSVM union is hidden when
the domain's nested-virtualization flag is clear.
Known Xen `spinlock_t` values are summarized as one line with lock state, ticket
head/tail, recursive owner, and recursion depth. Use `pahole` for full type
layouts.

Special value formatting is implemented as registered renderers. The Python API
accepts custom `renderers` and context-sensitive `selectors` in `SymbolFile`, so
types such as `spinlock_t`, `struct arch_domain`, and future Xen-specific types
can be handled without changing the generic DWARF walker.

From this repository, run the project commands from `scripts/crash-analyzer`,
or pass that directory to `uv` with `--project`.
