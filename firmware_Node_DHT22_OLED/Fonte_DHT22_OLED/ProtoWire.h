#pragma once
#include <Arduino.h>

// Codec protobuf wire-format 3: tags/varint, float32 little endian, strings.
// Contrato: common/ambiente.proto; sem dependencias dinamicas no ESP8266.
struct DiscoveryPacket {
  char gatewayIP[24];
  uint16_t announcePort;
  uint16_t telemetryPort;
};
struct ControlPacket {
  char sourceID[24];
  char command[24];
  bool enabled;
  uint32_t intervalMs;
  float threshold;
  bool failure;
  uint32_t requestID;
};

namespace ProtoWire {
  size_t encodeAnnouncement(uint8_t *output, size_t capacity,
                            const char *id, const char *kind, const char *ip,
                            bool controllable, bool enabled, uint32_t intervalMs,
                            float threshold, bool failure);
  size_t encodeTelemetry(uint8_t *output, size_t capacity, const char *id,
                         uint32_t seq, float temperature, float humidity,
                         uint64_t uptimeMs, bool alert);
  size_t encodeControlReply(uint8_t *output, size_t capacity, bool ok,
                            const char *message, bool enabled,
                            uint32_t intervalMs, float threshold,
                            bool failure, uint32_t requestID);
  bool decodeDiscovery(const uint8_t *data, size_t len, DiscoveryPacket &out);
  bool decodeControl(const uint8_t *data, size_t len, ControlPacket &out);
}
