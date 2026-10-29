#include "ProtoWire.h"
#include <string.h>

namespace {
class Writer {
public:
  Writer(uint8_t *out, size_t cap) : buf(out), capacity(cap) {}
  bool valid() const { return okay; }
  size_t size() const { return okay ? len : 0; }
  bool raw(uint8_t value) {
    if (!okay || len >= capacity) { okay = false; return false; }
    buf[len++] = value;
    return true;
  }
  bool varint(uint64_t value) {
    while (value >= 0x80) {
      if (!raw(static_cast<uint8_t>(value) | 0x80)) return false;
      value >>= 7;
    }
    return raw(static_cast<uint8_t>(value));
  }
  bool key(uint32_t field, uint8_t wire) { return varint((field << 3) | wire); }
  void stringField(uint32_t field, const char *text) {
    const size_t n = strlen(text);
    if (key(field, 2) && varint(n)) {
      for (size_t i = 0; i < n && okay; i++) raw(static_cast<uint8_t>(text[i]));
    }
  }
  void intField(uint32_t field, uint64_t value) {
    if (key(field, 0)) varint(value);
  }
  void boolField(uint32_t field, bool v) { intField(field, v ? 1 : 0); }
  void floatField(uint32_t field, float value) {
    if (!key(field, 5)) return;
    uint32_t u = 0;
    memcpy(&u, &value, sizeof(u));
    for (int i = 0; i < 4; i++) raw(static_cast<uint8_t>(u >> (8 * i)));
  }
private:
  uint8_t *buf;
  size_t capacity;
  size_t len = 0;
  bool okay = true;
};

class Reader {
public:
  Reader(const uint8_t *data, size_t length) : buf(data), cap(length) {}
  bool valid() const { return okay; }
  bool more() const { return okay && pos < cap; }
  bool varint(uint64_t &out) {
    out = 0;
    for (uint8_t shift = 0; shift <= 63; shift += 7) {
      if (pos >= cap) return okay = false;
      const uint8_t b = buf[pos++];
      out |= static_cast<uint64_t>(b & 0x7f) << shift;
      if (!(b & 0x80)) return true;
      if (shift == 63) break;
    }
    return okay = false;
  }
  bool tag(uint32_t &field, uint8_t &wire) {
    uint64_t value;
    if (!varint(value) || value < 8 || (value & 7) > 5) return okay = false;
    field = static_cast<uint32_t>(value >> 3);
    wire = static_cast<uint8_t>(value & 7);
    return true;
  }
  bool string(char *output, size_t capacity) {
    uint64_t count;
    if (!varint(count) || count > cap - pos || capacity == 0) return okay = false;
    size_t copy = count < capacity - 1 ? static_cast<size_t>(count) : capacity - 1;
    memcpy(output, buf + pos, copy);
    output[copy] = '\0';
    pos += static_cast<size_t>(count);
    return true;
  }
  bool integer(uint32_t &value) {
    uint64_t tmp;
    if (!varint(tmp)) return false;
    value = static_cast<uint32_t>(tmp);
    return true;
  }
  bool floating(float &out) {
    if (cap - pos < 4) return okay = false;
    uint32_t u = 0;
    for (uint8_t i = 0; i < 4; i++) u |= static_cast<uint32_t>(buf[pos++]) << (8 * i);
    memcpy(&out, &u, sizeof(out));
    return true;
  }
  bool skip(uint8_t wire) {
    uint64_t n;
    switch (wire) {
      case 0: return varint(n);
      case 1: n = 8; break;
      case 2: if (!varint(n)) return false; break;
      case 5: n = 4; break;
      default: return okay = false;
    }
    if (n > cap - pos) return okay = false;
    pos += static_cast<size_t>(n);
    return true;
  }
private:
  const uint8_t *buf;
  size_t cap;
  size_t pos = 0;
  bool okay = true;
};
}

size_t ProtoWire::encodeAnnouncement(uint8_t *out, size_t cap,
  const char *id, const char *kind, const char *ip,
  bool ctrl, bool enabled, uint32_t interval, float threshold, bool failure) {
  Writer w(out, cap);
  w.stringField(1, id);
  w.stringField(2, kind);
  w.stringField(3, ip);
  w.boolField(4, ctrl);
  w.intField(5, 0);            // gRPC externo anunciado pelo bridge
  w.stringField(6, "");
  w.boolField(7, enabled);
  w.intField(8, interval);
  w.boolField(9, failure);
  w.floatField(10, threshold);
  return w.size();
}

size_t ProtoWire::encodeTelemetry(uint8_t *out, size_t cap, const char *id,
  uint32_t seq, float t, float h, uint64_t ms, bool alert) {
  Writer w(out, cap);
  w.stringField(1, id);
  w.intField(2, seq);
  w.floatField(3, t);
  w.floatField(4, h);
  w.intField(5, ms);
  w.boolField(6, alert);
  return w.size();
}

size_t ProtoWire::encodeControlReply(uint8_t *out, size_t cap,
  bool ok, const char *message, bool enabled, uint32_t interval,
  float threshold, bool failure, uint32_t requestID) {
  Writer w(out, cap);
  w.boolField(1, ok);
  w.stringField(2, message);
  w.boolField(3, enabled);
  w.intField(4, interval);
  w.floatField(5, threshold);
  w.boolField(6, failure);
  w.intField(7, requestID);
  return w.size();
}

bool ProtoWire::decodeDiscovery(const uint8_t *data, size_t len, DiscoveryPacket &out) {
  memset(&out, 0, sizeof(out));
  Reader reader(data, len);
  while (reader.more()) {
    uint32_t field; uint8_t wire; uint32_t value;
    if (!reader.tag(field, wire)) return false;
    if (field == 1 && wire == 2) {
      if (!reader.string(out.gatewayIP, sizeof(out.gatewayIP))) return false;
    } else if ((field == 2 || field == 3) && wire == 0) {
      if (!reader.integer(value)) return false;
      if (value > 65535) return false;
      if (field == 2) out.announcePort = value;
      else out.telemetryPort = value;
    } else if (!reader.skip(wire)) return false;
  }
  return reader.valid() && out.gatewayIP[0];
}

bool ProtoWire::decodeControl(const uint8_t *data, size_t len, ControlPacket &out) {
  memset(&out, 0, sizeof(out));
  Reader reader(data, len);
  while (reader.more()) {
    uint32_t field; uint8_t wire; uint32_t value;
    if (!reader.tag(field, wire)) return false;
    if (wire == 2 && field == 1) {
      if (!reader.string(out.sourceID, sizeof(out.sourceID))) return false;
    } else if (wire == 2 && field == 2) {
      if (!reader.string(out.command, sizeof(out.command))) return false;
    } else if (wire == 5 && field == 5) {
      if (!reader.floating(out.threshold)) return false;
    } else if (wire == 0 && (field == 3 || field == 4 || field == 6 || field == 7)) {
      if (!reader.integer(value)) return false;
      switch (field) {
        case 3: out.enabled = value != 0; break;
        case 4: out.intervalMs = value; break;
        case 6: out.failure = value != 0; break;
        case 7: out.requestID = value; break;
      }
    } else if (!reader.skip(wire)) return false;
  }
  return reader.valid() && out.command[0];
}
