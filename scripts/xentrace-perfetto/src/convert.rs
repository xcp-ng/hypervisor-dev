//! Turns TSC-ordered xentrace records into Perfetto tracks and events.
//!
//! Layout:
//! - "Physical CPUs" group, one track per pCPU: a slice per vCPU running on
//!   it, with nested VM exit / C-state slices and every other event as an
//!   instant. Plus a frequency counter per pCPU.
//! - One process per domain and one thread per vCPU, with runstate slices
//!   (running / runnable / blocked / offline).

use crate::events::*;
use crate::perfetto::{Arg, EventType, TraceWriter, TrackKind};
use crate::xentrace::Record;
use std::borrow::Cow;
use std::collections::{HashMap, HashSet};
use std::io::{self, Write};

const PCPU_GROUP_UUID: u64 = 1;
const PCPU_UUID_BASE: u64 = 0x1_0000;
const FREQ_UUID_BASE: u64 = 0x2_0000;
const DOMAIN_UUID_BASE: u64 = 0x1_0000_0000;
const VCPU_UUID_BASE: u64 = 0x2_0000_0000;

#[derive(Clone, Copy, PartialEq, Eq, Hash)]
struct Vcpu {
    dom: u32,
    vcpu: u32,
}

impl Vcpu {
    fn from_word(w: u32) -> Self {
        Self {
            dom: w >> 16,
            vcpu: w & 0xffff,
        }
    }
    fn label(self) -> String {
        if self.dom == DOMID_IDLE {
            format!("idle v{}", self.vcpu)
        } else {
            format!("d{}v{}", self.dom, self.vcpu)
        }
    }
    // Perfetto treats pid/tid 0 specially, so offset everything by one.
    fn pid(self) -> i32 {
        self.dom as i32 + 1
    }
    fn tid(self) -> i64 {
        ((self.dom as i64 + 1) << 16) | self.vcpu as i64
    }
    fn uuid(self) -> u64 {
        VCPU_UUID_BASE + ((self.dom as u64) << 16 | self.vcpu as u64)
    }
}

#[derive(Default)]
struct Pcpu {
    running: Option<Vcpu>,
    /// A VM exit or C-state slice nested inside `running` (or top-level if
    /// the trace started while the vCPU was already running).
    inner: Option<Inner>,
    freq_track: bool,
}

#[derive(Clone, Copy, PartialEq)]
enum Inner {
    Exit,
    Idle,
}

#[derive(Default)]
pub struct Stats {
    pub records: u64,
    pub lost_records: u64,
    pub vmexits: u64,
    pub runstate_changes: u64,
}

pub struct Converter<W: Write> {
    out: TraceWriter<W>,
    cpu_hz: u64,
    instants: bool,
    pcpus: Vec<Pcpu>,
    domains: HashSet<u32>,
    vcpus: HashMap<Vcpu, bool>,
    names: HashMap<u32, Cow<'static, str>>,
    last_ts: u64,
    pub stats: Stats,
}

impl<W: Write> Converter<W> {
    pub fn new(out: W, cpu_hz: u64, instants: bool) -> io::Result<Self> {
        let mut out = TraceWriter::new(out);
        out.track(
            PCPU_GROUP_UUID,
            "Physical CPUs",
            TrackKind::Plain {
                parent: None,
                rank: None,
                ordered_children: true,
            },
        )?;
        Ok(Self {
            out,
            cpu_hz,
            instants,
            pcpus: Vec::new(),
            domains: HashSet::new(),
            vcpus: HashMap::new(),
            names: HashMap::new(),
            last_ts: 0,
            stats: Stats::default(),
        })
    }

    fn ns(&self, tsc: u64) -> u64 {
        (tsc as u128 * 1_000_000_000 / self.cpu_hz as u128) as u64
    }

    fn pcpu(&mut self, cpu: u32) -> io::Result<u64> {
        let i = cpu as usize;
        if self.pcpus.len() <= i {
            for n in self.pcpus.len()..=i {
                self.out.track(
                    PCPU_UUID_BASE + n as u64,
                    &format!("CPU {n}"),
                    TrackKind::Plain {
                        parent: Some(PCPU_GROUP_UUID),
                        rank: Some(n as i32),
                        ordered_children: false,
                    },
                )?;
                self.pcpus.push(Pcpu::default());
            }
        }
        Ok(PCPU_UUID_BASE + cpu as u64)
    }

    /// Returns the vCPU's track, declaring it (and its domain) on first use.
    fn vcpu_track(&mut self, v: Vcpu) -> io::Result<u64> {
        if self.domains.insert(v.dom) {
            let name = if v.dom == DOMID_IDLE {
                "idle".to_owned()
            } else {
                format!("d{}", v.dom)
            };
            self.out.track(
                DOMAIN_UUID_BASE + v.dom as u64,
                &name,
                TrackKind::Process { pid: v.pid() },
            )?;
        }
        if !self.vcpus.contains_key(&v) {
            self.out.track(
                v.uuid(),
                &format!("vcpu {}", v.vcpu),
                TrackKind::Thread {
                    pid: v.pid(),
                    tid: v.tid(),
                },
            )?;
            self.vcpus.insert(v, false);
        }
        Ok(v.uuid())
    }

    fn end(&mut self, ts: u64, track: u64) -> io::Result<()> {
        self.out.event(ts, track, EventType::SliceEnd, "", &[])
    }

    fn close_inner(&mut self, ts: u64, cpu: u32) -> io::Result<()> {
        if self.pcpus[cpu as usize].inner.take().is_some() {
            self.end(ts, PCPU_UUID_BASE + cpu as u64)?;
        }
        Ok(())
    }

    fn close_running(&mut self, ts: u64, cpu: u32) -> io::Result<()> {
        self.close_inner(ts, cpu)?;
        if self.pcpus[cpu as usize].running.take().is_some() {
            self.end(ts, PCPU_UUID_BASE + cpu as u64)?;
        }
        Ok(())
    }

    pub fn process(&mut self, r: &Record) -> io::Result<()> {
        self.stats.records += 1;
        let ts = self.ns(r.tsc);
        self.last_ts = self.last_ts.max(ts);
        let cpu = r.cpu;
        let track = self.pcpu(cpu)?;
        let ev = normalize(r.event);

        if r.event & RUNSTATE_CHANGE_MASK == TRC_SCHED_RUNSTATE_CHANGE {
            return self.runstate_change(ts, r);
        }

        match ev {
            TRC_HVM_VMENTRY => {
                if self.pcpus[cpu as usize].inner == Some(Inner::Exit) {
                    self.close_inner(ts, cpu)?;
                }
            }
            TRC_HVM_VMX_EXIT | TRC_HVM_SVM_EXIT => {
                self.stats.vmexits += 1;
                self.close_inner(ts, cpu)?;
                let reason = r.d(0);
                let name: Cow<str> = if ev == TRC_HVM_VMX_EXIT {
                    vmx_exit_name(reason).map(Cow::from)
                } else {
                    svm_exit_name(reason)
                }
                .unwrap_or_else(|| format!("exit {reason:#x}").into());
                let rip = if r.event & TRC_64_FLAG != 0 {
                    r.d64(1)
                } else {
                    r.d(1) as u64
                };
                self.out.event(
                    ts,
                    track,
                    EventType::SliceBegin,
                    &name,
                    &[
                        ("exit_reason", Arg::Uint(reason as u64)),
                        ("rip", Arg::Pointer(rip)),
                    ],
                )?;
                self.pcpus[cpu as usize].inner = Some(Inner::Exit);
            }
            TRC_PM_IDLE_ENTRY => {
                self.close_inner(ts, cpu)?;
                self.out.event(
                    ts,
                    track,
                    EventType::SliceBegin,
                    &format!("C{}", r.d(0)),
                    &[],
                )?;
                self.pcpus[cpu as usize].inner = Some(Inner::Idle);
            }
            TRC_PM_IDLE_EXIT => {
                if self.pcpus[cpu as usize].inner == Some(Inner::Idle) {
                    self.close_inner(ts, cpu)?;
                }
            }
            TRC_PM_FREQ_CHANGE => {
                let freq_track = FREQ_UUID_BASE + cpu as u64;
                if !self.pcpus[cpu as usize].freq_track {
                    self.pcpus[cpu as usize].freq_track = true;
                    self.out.track(
                        freq_track,
                        &format!("CPU {cpu} frequency"),
                        TrackKind::Counter {
                            parent: Some(PCPU_GROUP_UUID),
                        },
                    )?;
                }
                self.out.counter(ts, freq_track, r.d(1) as i64)?;
            }
            TRC_PV_HYPERCALL_V2 => {
                if self.instants {
                    self.hypercall(ts, track, r)?;
                }
            }
            _ => {
                if ev == TRC_LOST_RECORDS {
                    self.stats.lost_records += r.d(0) as u64;
                }
                if self.instants || ev == TRC_LOST_RECORDS {
                    self.generic(ts, track, r)?;
                }
            }
        }
        Ok(())
    }

    fn runstate_change(&mut self, ts: u64, r: &Record) -> io::Result<()> {
        self.stats.runstate_changes += 1;
        let old = (r.event >> 8) & 3;
        let new = (r.event >> 4) & 3;
        let v = Vcpu::from_word(r.d(0));
        let cpu = r.cpu;

        // vCPU track: one slice per runstate.
        let vtrack = self.vcpu_track(v)?;
        if self.vcpus.insert(v, true) == Some(true) {
            self.end(ts, vtrack)?;
        }
        self.out.event(
            ts,
            vtrack,
            EventType::SliceBegin,
            runstate_name(new),
            &[("pcpu", Arg::Uint(cpu as u64))],
        )?;

        // pCPU track: one slice per vCPU occupying the CPU. Both transitions
        // are logged on the pCPU doing the context switch.
        let p = &self.pcpus[cpu as usize];
        if old == RUNSTATE_RUNNING && p.running == Some(v) {
            self.close_running(ts, cpu)?;
        }
        if new == RUNSTATE_RUNNING {
            self.close_running(ts, cpu)?;
            self.out.event(
                ts,
                PCPU_UUID_BASE + cpu as u64,
                EventType::SliceBegin,
                &v.label(),
                &[
                    ("domid", Arg::Uint(v.dom as u64)),
                    ("vcpu", Arg::Uint(v.vcpu as u64)),
                ],
            )?;
            self.pcpus[cpu as usize].running = Some(v);
        }
        Ok(())
    }

    fn hypercall(&mut self, ts: u64, track: u64, r: &Record) -> io::Result<()> {
        let op = r.d(0) & 0xfffff;
        let name = match hypercall_name(op) {
            Some(n) => format!("hypercall {n}"),
            None => format!("hypercall {op}"),
        };
        // Bits 20+2i encode whether argument i is absent, 32- or 64-bit.
        const ARG_NAMES: [&str; 6] = ["a0", "a1", "a2", "a3", "a4", "a5"];
        let mut args = vec![("op", Arg::Uint(op as u64))];
        let mut w = 1;
        for (i, arg_name) in ARG_NAMES.iter().enumerate() {
            match (r.d(0) >> (20 + 2 * i)) & 3 {
                1 => {
                    args.push((arg_name, Arg::Uint(r.d(w) as u64)));
                    w += 1;
                }
                2 => {
                    args.push((arg_name, Arg::Uint(r.d64(w))));
                    w += 2;
                }
                _ => {}
            }
        }
        self.out.event(ts, track, EventType::Instant, &name, &args)
    }

    fn generic(&mut self, ts: u64, track: u64, r: &Record) -> io::Result<()> {
        const ARG_NAMES: [&str; 7] = ["d0", "d1", "d2", "d3", "d4", "d5", "d6"];
        let name = self
            .names
            .entry(r.event)
            .or_insert_with(|| event_name(r.event));
        let mut args = [("", Arg::Uint(0)); 7];
        for (a, (&d, n)) in args.iter_mut().zip(r.data().iter().zip(ARG_NAMES)) {
            *a = (n, Arg::Uint(d as u64));
        }
        self.out
            .event(ts, track, EventType::Instant, name, &args[..r.data().len()])
    }

    /// Close every open slice at the last timestamp and flush.
    pub fn finish(mut self) -> io::Result<Stats> {
        let ts = self.last_ts;
        for cpu in 0..self.pcpus.len() as u32 {
            self.close_running(ts, cpu)?;
        }
        let open: Vec<Vcpu> = self
            .vcpus
            .iter()
            .filter(|&(_, &open)| open)
            .map(|(&v, _)| v)
            .collect();
        for v in open {
            self.end(ts, v.uuid())?;
        }
        self.out.finish()?;
        Ok(self.stats)
    }
}
