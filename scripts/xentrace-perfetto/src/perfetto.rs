//! Streaming writer for Perfetto's protobuf trace format.
//!
//! A trace file is `message Trace { repeated TracePacket packet = 1; }`, so
//! packets can be appended one at a time and memory use stays flat.
//! Field numbers come from perfetto/protos/perfetto/trace/perfetto_trace.proto.

use crate::proto::Msg;
use std::collections::HashMap;
use std::io::{self, Write};

// Trace
const TRACE_PACKET: u32 = 1;
// TracePacket
const PKT_TIMESTAMP: u32 = 8;
const PKT_SEQUENCE_ID: u32 = 10;
const PKT_TRACK_EVENT: u32 = 11;
const PKT_INTERNED_DATA: u32 = 12;
const PKT_SEQUENCE_FLAGS: u32 = 13;
const PKT_TRACK_DESCRIPTOR: u32 = 60;
const SEQ_INCREMENTAL_STATE_CLEARED: u64 = 1;
const SEQ_NEEDS_INCREMENTAL_STATE: u64 = 2;
// TrackDescriptor
const TD_UUID: u32 = 1;
const TD_NAME: u32 = 2;
const TD_PROCESS: u32 = 3;
const TD_THREAD: u32 = 4;
const TD_PARENT_UUID: u32 = 5;
const TD_COUNTER: u32 = 8;
const TD_CHILD_ORDERING: u32 = 11;
const TD_SIBLING_ORDER_RANK: u32 = 12;
const CHILD_ORDERING_EXPLICIT: u64 = 3;
// ProcessDescriptor / ThreadDescriptor
const PD_PID: u32 = 1;
const PD_PROCESS_NAME: u32 = 6;
const THD_PID: u32 = 1;
const THD_TID: u32 = 2;
const THD_THREAD_NAME: u32 = 5;
// TrackEvent
const TE_DEBUG_ANNOTATIONS: u32 = 4;
const TE_TYPE: u32 = 9;
const TE_NAME_IID: u32 = 10;
const TE_TRACK_UUID: u32 = 11;
const TE_COUNTER_VALUE: u32 = 30;
// DebugAnnotation
const DA_NAME_IID: u32 = 1;
const DA_UINT_VALUE: u32 = 3;
const DA_POINTER_VALUE: u32 = 7;
// InternedData
const ID_EVENT_NAMES: u32 = 2;
const ID_DEBUG_ANNOTATION_NAMES: u32 = 3;
// EventName / DebugAnnotationName
const IN_IID: u32 = 1;
const IN_NAME: u32 = 2;

const SEQUENCE_ID: u64 = 1;

#[derive(Clone, Copy)]
pub enum EventType {
    SliceBegin = 1,
    SliceEnd = 2,
    Instant = 3,
    Counter = 4,
}

#[derive(Clone, Copy)]
pub enum Arg {
    Uint(u64),
    Pointer(u64),
}

pub enum TrackKind {
    Plain {
        parent: Option<u64>,
        rank: Option<i32>,
        ordered_children: bool,
    },
    Process {
        pid: i32,
    },
    Thread {
        pid: i32,
        tid: i64,
    },
    Counter {
        parent: Option<u64>,
    },
}

pub struct TraceWriter<W: Write> {
    out: W,
    first_packet: bool,
    event_names: HashMap<String, u64>,
    arg_names: HashMap<&'static str, u64>,
    // Scratch buffers reused across events to avoid allocating per packet.
    pkt: Msg,
    te: Msg,
    interned: Msg,
    tmp: Msg,
    frame: Msg,
}

impl<W: Write> TraceWriter<W> {
    pub fn new(out: W) -> Self {
        Self {
            out,
            first_packet: true,
            event_names: HashMap::new(),
            arg_names: HashMap::new(),
            pkt: Msg::new(),
            te: Msg::new(),
            interned: Msg::new(),
            tmp: Msg::new(),
            frame: Msg::new(),
        }
    }

    /// Finish `self.pkt` and append it to the output as `Trace.packet`.
    fn write_packet(&mut self, needs_state: bool) -> io::Result<()> {
        self.pkt.uint(PKT_SEQUENCE_ID, SEQUENCE_ID);
        let mut flags = 0;
        if self.first_packet {
            flags |= SEQ_INCREMENTAL_STATE_CLEARED;
            self.first_packet = false;
        }
        if needs_state {
            flags |= SEQ_NEEDS_INCREMENTAL_STATE;
        }
        if flags != 0 {
            self.pkt.uint(PKT_SEQUENCE_FLAGS, flags);
        }
        self.frame.clear();
        self.frame.msg(TRACE_PACKET, &self.pkt);
        self.out.write_all(self.frame.as_bytes())
    }

    pub fn track(&mut self, uuid: u64, name: &str, kind: TrackKind) -> io::Result<()> {
        let mut td = Msg::new();
        td.uint(TD_UUID, uuid);
        match kind {
            TrackKind::Plain {
                parent,
                rank,
                ordered_children,
            } => {
                td.string(TD_NAME, name);
                if let Some(p) = parent {
                    td.uint(TD_PARENT_UUID, p);
                }
                if let Some(r) = rank {
                    td.int(TD_SIBLING_ORDER_RANK, r as i64);
                }
                if ordered_children {
                    td.uint(TD_CHILD_ORDERING, CHILD_ORDERING_EXPLICIT);
                }
            }
            TrackKind::Process { pid } => {
                let mut pd = Msg::new();
                pd.int(PD_PID, pid as i64).string(PD_PROCESS_NAME, name);
                td.msg(TD_PROCESS, &pd);
            }
            TrackKind::Thread { pid, tid } => {
                let mut thd = Msg::new();
                thd.int(THD_PID, pid as i64)
                    .int(THD_TID, tid)
                    .string(THD_THREAD_NAME, name);
                td.msg(TD_THREAD, &thd);
            }
            TrackKind::Counter { parent } => {
                td.string(TD_NAME, name);
                if let Some(p) = parent {
                    td.uint(TD_PARENT_UUID, p);
                }
                td.msg(TD_COUNTER, &Msg::new());
            }
        }
        self.pkt.clear();
        self.pkt.msg(PKT_TRACK_DESCRIPTOR, &td);
        self.write_packet(false)
    }

    /// Emit a TrackEvent. `name` is ignored for slice ends.
    pub fn event(
        &mut self,
        ts_ns: u64,
        track: u64,
        ty: EventType,
        name: &str,
        args: &[(&'static str, Arg)],
    ) -> io::Result<()> {
        self.interned.clear();
        self.te.clear();
        self.te.uint(TE_TYPE, ty as u64).uint(TE_TRACK_UUID, track);

        if !matches!(ty, EventType::SliceEnd) {
            let iid = match self.event_names.get(name) {
                Some(&iid) => iid,
                None => {
                    let iid = self.event_names.len() as u64 + 1;
                    self.event_names.insert(name.to_owned(), iid);
                    self.tmp.clear();
                    self.tmp.uint(IN_IID, iid).string(IN_NAME, name);
                    self.interned.msg(ID_EVENT_NAMES, &self.tmp);
                    iid
                }
            };
            self.te.uint(TE_NAME_IID, iid);
        }

        for &(arg_name, value) in args {
            let iid = match self.arg_names.get(arg_name) {
                Some(&iid) => iid,
                None => {
                    let iid = self.arg_names.len() as u64 + 1;
                    self.arg_names.insert(arg_name, iid);
                    self.tmp.clear();
                    self.tmp.uint(IN_IID, iid).string(IN_NAME, arg_name);
                    self.interned.msg(ID_DEBUG_ANNOTATION_NAMES, &self.tmp);
                    iid
                }
            };
            self.tmp.clear();
            self.tmp.uint(DA_NAME_IID, iid);
            match value {
                Arg::Uint(v) => self.tmp.uint(DA_UINT_VALUE, v),
                Arg::Pointer(v) => self.tmp.uint(DA_POINTER_VALUE, v),
            };
            self.te.msg(TE_DEBUG_ANNOTATIONS, &self.tmp);
        }

        self.pkt.clear();
        self.pkt
            .uint(PKT_TIMESTAMP, ts_ns)
            .msg(PKT_TRACK_EVENT, &self.te);
        if !self.interned.as_bytes().is_empty() {
            self.pkt.msg(PKT_INTERNED_DATA, &self.interned);
        }
        self.write_packet(true)
    }

    pub fn counter(&mut self, ts_ns: u64, track: u64, value: i64) -> io::Result<()> {
        self.te.clear();
        self.te
            .uint(TE_TYPE, EventType::Counter as u64)
            .uint(TE_TRACK_UUID, track)
            .int(TE_COUNTER_VALUE, value);
        self.pkt.clear();
        self.pkt
            .uint(PKT_TIMESTAMP, ts_ns)
            .msg(PKT_TRACK_EVENT, &self.te);
        self.write_packet(false)
    }

    pub fn finish(mut self) -> io::Result<W> {
        self.out.flush()?;
        Ok(self.out)
    }
}
