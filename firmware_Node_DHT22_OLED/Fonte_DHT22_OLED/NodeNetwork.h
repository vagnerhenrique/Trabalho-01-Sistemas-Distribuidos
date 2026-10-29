#pragma once
#include <Arduino.h>
namespace NodeNetwork {
  // Status de rede para exibicao local. Nao confundir Wi-Fi conectado
  // com Gateway descoberto por multicast.
  struct NetworkDisplayStatus {
    bool wifiConnected;
    bool gatewayDiscovered;
    String ssid;
    String ip;
    int32_t rssiDbm;
  };
  NetworkDisplayStatus displayStatus();
  void begin();
  void tick();
  void sendMeasurement(float temperatureC, float humidity, uint32_t sequence, bool alert);
  bool connected();
  bool telemetryEnabled();
  bool sourceEnabled();
  float alertThreshold();
  uint32_t sendIntervalMs();
}
