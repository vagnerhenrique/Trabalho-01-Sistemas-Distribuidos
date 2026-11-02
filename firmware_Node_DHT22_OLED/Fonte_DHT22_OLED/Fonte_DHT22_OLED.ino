#include <Arduino.h>
#include <math.h>
#include "Config.h"
#include "SensorDHT.h"
#include "DisplayOLED.h"
#include "NodeNetwork.h"

namespace {
uint32_t lastRead = 0;
uint32_t lastSent = 0;
uint32_t lastScreenSwitch = 0;
uint32_t lastNetworkScreenDraw = 0;
uint32_t sequence = 0;
float previousTemp = NAN;
SensorReading latestSample = {};
bool latestSampleValid = false;
bool displayReady = false;
bool networkPage = false;  // inicializa na tela do sensor

void drawCurrentPage() {
  if (!displayReady) return;

  if (networkPage) {
    const NodeNetwork::NetworkDisplayStatus status = NodeNetwork::displayStatus();
    DisplayOLED::showNetworkInfo(status.ssid, status.ip,
                                 status.wifiConnected, status.gatewayDiscovered,
                                 status.rssiDbm);
  } else if (latestSampleValid) {
    DisplayOLED::showReadings(latestSample.temperatureC,
                              latestSample.humidityPercent, sequence);
  } else {
    DisplayOLED::showSensorError();
  }
}
} // namespace

void setup() {
  Serial.begin(115200);
  delay(150);
  Serial.printf("\n=== TRABALHO 01 - %s ===\n", SOURCE_ID);
  displayReady = DisplayOLED::begin();
  if (displayReady) DisplayOLED::showStartup();
  else Serial.println("OLED nao encontrado. Confira SDA=D5 SCL=D6, 0x3C");

  SensorDHT::begin();
  NodeNetwork::begin();

  const uint32_t now = millis();
  lastRead = now - READ_INTERVAL_MS; // leitura inicial imediata
  lastScreenSwitch = now;
  lastNetworkScreenDraw = now;
  
}

void loop() {
  // Rede e descoberta multicast continuam ativas nas duas telas.
  NodeNetwork::tick();
  const uint32_t now = millis();

  // Alternancia independente da leitura do DHT22 e do envio ao Gateway.
  if (now - lastScreenSwitch >= OLED_PAGE_INTERVAL_MS) {
    lastScreenSwitch = now;
    networkPage = !networkPage;
    drawCurrentPage();
    lastNetworkScreenDraw = now;
  } else if (networkPage &&
             now - lastNetworkScreenDraw >= OLED_NETWORK_REFRESH_MS) {
    // A tela de rede acompanha conexoes/reconexoes e mudancas de IP.
    lastNetworkScreenDraw = now;
    drawCurrentPage();
  }

  if (now - lastRead < READ_INTERVAL_MS) return;
  lastRead = now;

  SensorReading sample;
  if (!SensorDHT::read(sample)) {
    latestSampleValid = false;
    Serial.println("Falha na leitura DHT22");
    if (!networkPage) drawCurrentPage();
    return;
  }

  latestSample = sample;
  latestSampleValid = true;
  ++sequence;
  if (!networkPage) drawCurrentPage();

  const NodeNetwork::NetworkDisplayStatus net = NodeNetwork::displayStatus();
  Serial.printf("[%s] seq=%lu temperatura=%.1fC umidade=%.1f%% WiFi=%d IP=%s Gateway=%d\n",
    SOURCE_ID, static_cast<unsigned long>(sequence), sample.temperatureC,
    sample.humidityPercent, net.wifiConnected, net.ip.c_str(), net.gatewayDiscovered);

  const float threshold = NodeNetwork::alertThreshold();
  const bool crossing = !isnan(previousTemp) &&
                        previousTemp < threshold &&
                        sample.temperatureC >= threshold;
  previousTemp = sample.temperatureC;
  if (NodeNetwork::telemetryEnabled() &&
      (crossing || (now - lastSent >= NodeNetwork::sendIntervalMs()))) {
    NodeNetwork::sendMeasurement(sample.temperatureC, sample.humidityPercent,
                                 sequence, crossing);
    lastSent = now;
  }
}
