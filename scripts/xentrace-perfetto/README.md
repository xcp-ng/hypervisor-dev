# xentrace-perfetto

Convert [xentrace](https://xenbits.xen.org/docs/unstable/man/xentrace.8.html)
binary traces into [Perfetto](https://perfetto.dev) traces, to browse Xen
scheduling and VM exits on a timeline in <https://ui.perfetto.dev> or query them
with `trace_processor` SQL.

No dependencies; the Perfetto protobuf is encoded by hand (`src/proto.rs`).

## Usage

```sh
cargo build --release

# On the Xen host (cpu_mhz is the TSC frequency used for timestamps):
xl info | grep cpu_mhz
# On Xen/XCP-ng host, generate traces (all events, 10 seconds)
xentrace -D -e all -T 10 trace.bin
# Separately, convert the trace binary into perfetto trace.
xentrace-perfetto --cpu-mhz <cpu_mhz> trace.bin trace.pftrace

# Or streaming, without an intermediate file (-T stops xentrace cleanly):
xentrace -D -e all -T 10 | xentrace-perfetto --cpu-mhz <cpu_mhz> - trace.pftrace
```

Options:

- `--no-instants`: only emit slices and counters; much smaller output.
- `--reorder-window-ms <MS>` (default 500): xentrace writes one per-CPU buffer
  at a time, so records from different CPUs arrive out of order by up to
  roughly the poll period (`xentrace -s`, 100 ms by default). The tool
  merges them back into timestamp order within this window. Raise it if the
  tool warns about late records.

Try it without a Xen host:

```sh
python3 scripts/synthetic-trace.py > synth.bin
cargo run --release -- --cpu-mhz 2000 synth.bin synth.pftrace
```

## What you get

- **Physical CPUs**: one track per pCPU, with
  - a slice per vCPU running on it (`d1v0`, `idle v3`, ...), from runstate changes;
  - nested inside, a slice per HVM VM exit (`VMEXIT` → `VMENTRY`), named after the
    VMX/SVM exit reason, with `exit_reason` and `rip` args;
  - nested C-state slices (`C2`, ...) from `pm_idle_entry`/`pm_idle_exit`;
  - every other event as an instant, with its raw payload words as `d0`..`d6`
    (PV `hypercall_v2` is decoded into op name and arguments);
  - a frequency counter track when `pm_freq_change` events are present.
- **One process per domain, one thread per vCPU** with its runstate as
  slices: `running`, `runnable`, `blocked`, `offline`.

## Limitations

- Records are assumed little-endian (all current Xen hosts).
- TSC is assumed invariant and synchronised across CPUs, and timestamps are
  `tsc / cpu_mhz` (time since TSC reset, not wall-clock time).
- Slices already open when tracing started (a vCPU that was already running,
  an exit in flight) are only partly shown: they start at the first event the
  trace has for them.
- HVM records don't say which vCPU they belong to; like xenalyze, they are
  attributed to whatever vCPU last started running on that pCPU.
- Only the event payloads needed for the slices are decoded (layouts taken
  from `tools/xentrace/xenalyze.c`); everything else shows raw words.

## Layout

| File | Role |
| --- | --- |
| `src/xentrace.rs` | Record reader (`struct t_rec`, CPU-change records) and the per-CPU reorder merge |
| `src/events.rs` | Event IDs and names from `trace.h`, exit reason and hypercall tables |
| `src/convert.rs` | State tracking that turns records into tracks, slices and instants |
| `src/perfetto.rs` | Streaming `TracePacket` writer with string interning |
| `src/proto.rs` | Minimal protobuf encoder |
