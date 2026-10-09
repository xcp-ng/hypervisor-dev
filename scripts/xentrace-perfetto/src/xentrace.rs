//! Reader for the binary stream written by `xentrace`.
//!
//! The stream is a sequence of `struct t_rec` (xen/include/public/trace.h):
//!
//! ```text
//! u32 header = event:28 | extra_u32:3 | cycles_included:1
//! [u32 tsc_lo, u32 tsc_hi]   if cycles_included
//! u32 extra[extra_u32]
//! ```
//!
//! xentrace dumps one per-CPU buffer window at a time, each window preceded by
//! a TRC_TRACE_CPU_CHANGE record `{ int cpu; unsigned window_size; }`
//! (tools/xentrace/xentrace.c). Records only carry their CPU implicitly, and
//! are only ordered within a CPU; see `Reorder` for the global merge.

use crate::events::TRC_TRACE_CPU_CHANGE;
use std::cmp::Reverse;
use std::collections::{BinaryHeap, VecDeque};
use std::io::{self, Read};

pub const TRACE_EXTRA_MAX: usize = 7;

#[derive(Clone, Debug)]
pub struct Record {
    pub cpu: u32,
    pub tsc: u64,
    pub event: u32,
    n_extra: u8,
    extra: [u32; TRACE_EXTRA_MAX],
    /// Position in the input, used as a tie-breaker to keep sorting stable.
    seq: u64,
}

impl Record {
    pub fn data(&self) -> &[u32] {
        &self.extra[..self.n_extra as usize]
    }

    /// Extra word `i`, or 0 if the record is shorter.
    pub fn d(&self, i: usize) -> u32 {
        self.data().get(i).copied().unwrap_or(0)
    }

    pub fn d64(&self, lo: usize) -> u64 {
        self.d(lo) as u64 | (self.d(lo + 1) as u64) << 32
    }
}

pub struct RecordReader<R> {
    input: R,
    cpu: u32,
    last_tsc: Vec<u64>,
    seq: u64,
    pub truncated: bool,
}

impl<R: Read> RecordReader<R> {
    pub fn new(input: R) -> Self {
        Self {
            input,
            cpu: 0,
            last_tsc: Vec::new(),
            seq: 0,
            truncated: false,
        }
    }

    /// Read `buf.len()` bytes; Ok(false) on a clean EOF at a record boundary.
    fn read_words(&mut self, buf: &mut [u32], at_boundary: bool) -> io::Result<bool> {
        let mut bytes = [0u8; 4 * (TRACE_EXTRA_MAX + 2)];
        let bytes = &mut bytes[..buf.len() * 4];
        let mut filled = 0;
        while filled < bytes.len() {
            match self.input.read(&mut bytes[filled..]) {
                Ok(0) => {
                    if !(at_boundary && filled == 0) {
                        self.truncated = true;
                    }
                    return Ok(false);
                }
                Ok(n) => filled += n,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => {}
                Err(e) => return Err(e),
            }
        }
        // xentrace writes host-endian data; Xen hosts are little-endian.
        for (w, &b) in buf.iter_mut().zip(bytes.as_chunks::<4>().0.iter()) {
            *w = u32::from_le_bytes(b);
        }
        Ok(true)
    }

    pub fn next_record(&mut self) -> io::Result<Option<Record>> {
        loop {
            let mut hdr = [0u32; 1];
            if !self.read_words(&mut hdr, true)? {
                return Ok(None);
            }
            let event = hdr[0] & 0x0fff_ffff;
            let n_extra = ((hdr[0] >> 28) & 0x7) as usize;
            let has_tsc = hdr[0] >> 31 != 0;

            let mut words = [0u32; TRACE_EXTRA_MAX + 2];
            let tsc_words = if has_tsc { 2 } else { 0 };
            if !self.read_words(&mut words[..tsc_words + n_extra], false)? {
                return Ok(None);
            }

            if event == TRC_TRACE_CPU_CHANGE && !has_tsc && n_extra == 2 {
                self.cpu = words[0];
                continue;
            }

            let cpu = self.cpu as usize;
            if self.last_tsc.len() <= cpu {
                self.last_tsc.resize(cpu + 1, 0);
            }
            if has_tsc {
                self.last_tsc[cpu] = words[0] as u64 | (words[1] as u64) << 32;
            }

            let mut extra = [0u32; TRACE_EXTRA_MAX];
            extra[..n_extra].copy_from_slice(&words[tsc_words..tsc_words + n_extra]);
            self.seq += 1;
            return Ok(Some(Record {
                cpu: self.cpu,
                // Records without a timestamp happened "at" the previous one.
                tsc: self.last_tsc[cpu],
                event,
                n_extra: n_extra as u8,
                extra,
                seq: self.seq,
            }));
        }
    }
}

/// Merges the per-CPU windows into one TSC-ordered stream.
///
/// Records are already ordered within a CPU, so this is a k-way merge of
/// per-CPU queues. The oldest head is released once a record `window` TSC
/// ticks newer has been seen: xentrace flushes every CPU once per poll
/// period, so a window of a few poll periods is enough. Anything arriving
/// later is still emitted (and counted in `late`) but may confuse the state
/// tracking.
pub struct Reorder {
    queues: Vec<VecDeque<Record>>,
    /// (head tsc, head seq, cpu) of every non-empty queue.
    heads: BinaryHeap<Reverse<(u64, u64, u32)>>,
    window: u64,
    max_tsc: u64,
    last_out: u64,
    pub late: u64,
}

impl Reorder {
    pub fn new(window: u64) -> Self {
        Self {
            queues: Vec::new(),
            heads: BinaryHeap::new(),
            window,
            max_tsc: 0,
            last_out: 0,
            late: 0,
        }
    }

    pub fn push(&mut self, rec: Record) {
        let cpu = rec.cpu as usize;
        if self.queues.len() <= cpu {
            self.queues.resize_with(cpu + 1, VecDeque::new);
        }
        self.max_tsc = self.max_tsc.max(rec.tsc);
        let q = &mut self.queues[cpu];
        if q.is_empty() {
            self.heads.push(Reverse((rec.tsc, rec.seq, rec.cpu)));
        }
        q.push_back(rec);
    }

    /// Next record that is safe to process; with `drain`, flush everything.
    pub fn pop(&mut self, drain: bool) -> Option<Record> {
        let &Reverse((tsc, _, cpu)) = self.heads.peek()?;
        if !drain && tsc.saturating_add(self.window) > self.max_tsc {
            return None;
        }
        self.heads.pop();
        let q = &mut self.queues[cpu as usize];
        let rec = q.pop_front()?;
        if let Some(next) = q.front() {
            self.heads.push(Reverse((next.tsc, next.seq, next.cpu)));
        }
        if rec.tsc < self.last_out {
            self.late += 1;
        }
        self.last_out = self.last_out.max(rec.tsc);
        Some(rec)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rec(words: &[u32]) -> Vec<u8> {
        words.iter().flat_map(|w| w.to_le_bytes()).collect()
    }

    #[test]
    fn parses_cpu_windows_and_tsc() {
        let mut buf = rec(&[TRC_TRACE_CPU_CHANGE | 2 << 28, 3, 0]);
        buf.extend(rec(&[0x8000_0000 | 1 << 28 | 0x0001_f00f, 100, 0, 42]));
        buf.extend(rec(&[0x0001_f00e]));
        let mut r = RecordReader::new(&buf[..]);
        let a = r.next_record().unwrap().unwrap();
        assert_eq!(
            (a.cpu, a.tsc, a.event, a.data()),
            (3, 100, 0x0001_f00f, &[42][..])
        );
        let b = r.next_record().unwrap().unwrap();
        assert_eq!((b.cpu, b.tsc, b.data().len()), (3, 100, 0));
        assert!(r.next_record().unwrap().is_none());
        assert!(!r.truncated);
    }

    #[test]
    fn reorder_merges_windows() {
        let mut buf = Vec::new();
        for (cpu, tscs) in [(0u32, [10u32, 30]), (1, [20, 40])] {
            buf.extend(rec(&[TRC_TRACE_CPU_CHANGE | 2 << 28, cpu, 0]));
            for t in tscs {
                buf.extend(rec(&[0x8000_0000 | 0x0001_f00f, t, 0]));
            }
        }
        let mut r = RecordReader::new(&buf[..]);
        let mut ro = Reorder::new(100);
        while let Some(x) = r.next_record().unwrap() {
            ro.push(x);
        }
        let out: Vec<u64> = std::iter::from_fn(|| ro.pop(true)).map(|r| r.tsc).collect();
        assert_eq!(out, [10, 20, 30, 40]);
        assert_eq!(ro.late, 0);
    }
}
