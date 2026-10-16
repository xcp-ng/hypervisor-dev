//! Minimal protobuf encoder, just enough to write Perfetto `TracePacket`s
//! without pulling in a protobuf toolchain.

#[derive(Default)]
pub struct Msg {
    buf: Vec<u8>,
}

const WT_VARINT: u32 = 0;
const WT_LEN: u32 = 2;

fn put_varint(buf: &mut Vec<u8>, mut v: u64) {
    while v >= 0x80 {
        buf.push((v as u8) | 0x80);
        v >>= 7;
    }
    buf.push(v as u8);
}

impl Msg {
    pub fn new() -> Self {
        Self::default()
    }

    fn key(&mut self, field: u32, wire_type: u32) {
        put_varint(&mut self.buf, ((field << 3) | wire_type) as u64);
    }

    pub fn uint(&mut self, field: u32, v: u64) -> &mut Self {
        self.key(field, WT_VARINT);
        put_varint(&mut self.buf, v);
        self
    }

    pub fn int(&mut self, field: u32, v: i64) -> &mut Self {
        self.uint(field, v as u64)
    }

    pub fn bytes(&mut self, field: u32, b: &[u8]) -> &mut Self {
        self.key(field, WT_LEN);
        put_varint(&mut self.buf, b.len() as u64);
        self.buf.extend_from_slice(b);
        self
    }

    pub fn string(&mut self, field: u32, s: &str) -> &mut Self {
        self.bytes(field, s.as_bytes())
    }

    pub fn msg(&mut self, field: u32, m: &Msg) -> &mut Self {
        self.bytes(field, &m.buf)
    }

    pub fn clear(&mut self) {
        self.buf.clear();
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.buf
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn varint_encoding() {
        let mut m = Msg::new();
        m.uint(1, 300);
        assert_eq!(m.as_bytes(), &[0x08, 0xac, 0x02]);
        let mut m = Msg::new();
        m.string(2, "hi");
        assert_eq!(m.as_bytes(), &[0x12, 0x02, b'h', b'i']);
    }
}
