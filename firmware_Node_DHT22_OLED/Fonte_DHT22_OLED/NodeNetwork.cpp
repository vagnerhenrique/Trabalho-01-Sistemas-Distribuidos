#include "NodeNetwork.h"
#include "Config.h"
#include "Secrets.h"
#include "ProtoWire.h"
#include <ESP8266WiFi.h>
#include <WiFiUdp.h>
#include <string.h>

namespace {
WiFiUDP multicastUDP;
WiFiUDP telemetryUDP;
WiFiUDP controlUDP;
WiFiUDP announcementUDP;
IPAddress multicastAddress(MULTICAST_IP[0], MULTICAST_IP[1], MULTICAST_IP[2], MULTICAST_IP[3]);
IPAddress gatewayIP;
bool multicastStarted = false;
bool controlStarted = false;
bool gatewayDiscovered = false;
bool enabled = true;
bool simulateFailure = false;
uint32_t intervalMs = DEFAULT_SEND_INTERVAL_MS;
float thresholdTempC = DEFAULT_ALERT_TEMP_C;
uint16_t announcePort = ANNOUNCE_PORT;
uint16_t telemetryPort = TELEMETRY_PORT;
uint32_t lastConnectAttempt = 0;
uint32_t lastAnnouncement = 0;
uint8_t messageBuffer[256];

// LED integrado do ESP8266 (normalmente D4 / GPIO2)
// LOW = LED aceso
// HIGH = LED apagado

void atualizarLedStatus() {
  if (!SOURCE_CONTROLLABLE) return;

  digitalWrite(
    LED_BUILTIN,
    enabled ? LOW : HIGH);
}

void announce() {
  if (!gatewayDiscovered || simulateFailure || WiFi.status() != WL_CONNECTED) return;
  const String ip = WiFi.localIP().toString();
  const size_t length = ProtoWire::encodeAnnouncement(messageBuffer, sizeof(messageBuffer),
                                                      SOURCE_ID, SOURCE_KIND, ip.c_str(), SOURCE_CONTROLLABLE,
                                                      enabled, intervalMs, thresholdTempC, simulateFailure);
  if (length && announcementUDP.beginPacket(gatewayIP, announcePort)) {
    announcementUDP.write(messageBuffer, length);
    announcementUDP.endPacket();
    lastAnnouncement = millis();
  }
}

void pollDiscovery() {
  const int packetLen = multicastUDP.parsePacket();
  if (packetLen <= 0) return;
  if (packetLen > static_cast<int>(sizeof(messageBuffer))) {
    while (multicastUDP.available()) multicastUDP.read();
    return;
  }
  const int received = multicastUDP.read(messageBuffer, packetLen);
  DiscoveryPacket request;
  if (received <= 0 || !ProtoWire::decodeDiscovery(messageBuffer, received, request)) return;
  IPAddress found;
  if (!found.fromString(request.gatewayIP)) return;
  gatewayIP = found;
  announcePort = request.announcePort ? request.announcePort : ANNOUNCE_PORT;
  telemetryPort = request.telemetryPort ? request.telemetryPort : TELEMETRY_PORT;
  gatewayDiscovered = true;
  Serial.printf("Gateway encontrado %s\n", gatewayIP.toString().c_str());
  announce();
  // Serial.printf("MAC Fonte A: %s\n", WiFi.macAddress().c_str());
}

void pollControl() {
  if (!SOURCE_CONTROLLABLE || !controlStarted) return;

  const int packetLen = controlUDP.parsePacket();
  if (packetLen <= 0) return;

  Serial.printf(
    "[CONTROLE] UDP recebido: %d bytes de %s:%u\n",
    packetLen,
    controlUDP.remoteIP().toString().c_str(),
    controlUDP.remotePort());


  if (packetLen > static_cast<int>(sizeof(messageBuffer))) {
    while (controlUDP.available()) controlUDP.read();
    return;
  }
  const IPAddress senderIP = controlUDP.remoteIP();
  const uint16_t senderPort = controlUDP.remotePort();
  const int received = controlUDP.read(messageBuffer, packetLen);
  ControlPacket request;

  if (received <= 0 || !ProtoWire::decodeControl(messageBuffer, received, request)) return;

  if (strcmp(request.sourceID, SOURCE_ID) != 0) return;
  bool ok = true;
  const char *replyText = "OK";
  if (!strcmp(request.command, "enabled")) {

    enabled = request.enabled;

    // Atualiza o LED conforme o comando recebido
    atualizarLedStatus();

    Serial.printf(
      "[LED] FONTE_A: %s\n",
      enabled ? "ACESO" : "APAGADO");
      
  } else if (!strcmp(request.command, "interval")) {
    if (request.intervalMs >= 2000 && request.intervalMs <= 3600000)
      intervalMs = request.intervalMs;
    else {
      ok = false;
      replyText = "Intervalo invalido";
    }
  } else if (!strcmp(request.command, "threshold")) thresholdTempC = request.threshold;
  else if (!strcmp(request.command, "failure")) simulateFailure = request.failure;
  else if (!strcmp(request.command, "status")) { /* nao altera estado */ } else {
    ok = false;
    replyText = "Comando invalido";
  }
  const size_t replyLength = ProtoWire::encodeControlReply(messageBuffer, sizeof(messageBuffer),
                                                           ok, replyText, enabled, intervalMs, thresholdTempC, simulateFailure, request.requestID);
  if (replyLength && controlUDP.beginPacket(senderIP, senderPort)) {
    controlUDP.write(messageBuffer, replyLength);
    controlUDP.endPacket();
  }
  Serial.printf("Controle: %s, sucesso=%d\n", request.command, ok);
  announce();
}

void startSockets() {

  if (WiFi.status() != WL_CONNECTED)
    return;

  // Inicializa o multicast apenas quando necessário
  if (!multicastStarted) {
    multicastStarted = multicastUDP.beginMulticast(
      WiFi.localIP(),
      multicastAddress,
      DISCOVERY_PORT);

    Serial.printf(
      "[REDE] Multicast iniciado: %d\n",
      multicastStarted);
  }

  // Inicializa o controle independentemente do multicast
  if (SOURCE_CONTROLLABLE && !controlStarted) {

    controlStarted = controlUDP.begin(CONTROL_PORT);

    Serial.printf(
      "[CONTROLE] Porta UDP=%u, iniciado=%d\n",
      CONTROL_PORT,
      controlStarted);
  }
}

}  // namespace

void NodeNetwork::begin() {

  // Inicialização do LED integrado
  if (SOURCE_CONTROLLABLE) {
    digitalWrite(LED_BUILTIN, HIGH);
    pinMode(LED_BUILTIN, OUTPUT);
    atualizarLedStatus();
  }

  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastConnectAttempt = millis();
  Serial.printf("Conectando WiFi SSID=%s\n", WIFI_SSID);
}

void NodeNetwork::tick() {
  if (WiFi.status() != WL_CONNECTED) {
    if (multicastStarted) multicastUDP.stop();
    if (controlStarted) controlUDP.stop();
    multicastStarted = false;
    controlStarted = false;
    gatewayDiscovered = false;
    if (millis() - lastConnectAttempt > 10000UL) {
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      lastConnectAttempt = millis();
      Serial.println("Reconectando WiFi...");
    }
    return;
  }
  startSockets();
  if (multicastStarted) pollDiscovery();
  pollControl();
  if (gatewayDiscovered && millis() - lastAnnouncement > 10000UL) announce();
}

NodeNetwork::NetworkDisplayStatus NodeNetwork::displayStatus() {
  NetworkDisplayStatus status;
  status.wifiConnected = (WiFi.status() == WL_CONNECTED);
  status.gatewayDiscovered = status.wifiConnected && gatewayDiscovered;
  // Enquanto desconectado, exibe a rede configurada como destino.
  status.ssid = status.wifiConnected ? WiFi.SSID() : String(WIFI_SSID);
  status.ip = status.wifiConnected ? WiFi.localIP().toString() : String("--");
  status.rssiDbm = status.wifiConnected ? WiFi.RSSI() : 0;
  return status;
}

bool NodeNetwork::connected() {
  return WiFi.status() == WL_CONNECTED && gatewayDiscovered;
}
bool NodeNetwork::sourceEnabled() {
  return enabled;
}
bool NodeNetwork::telemetryEnabled() {
  return connected() && enabled && !simulateFailure;
}
float NodeNetwork::alertThreshold() {
  return thresholdTempC;
}
uint32_t NodeNetwork::sendIntervalMs() {
  return intervalMs;
}

void NodeNetwork::sendMeasurement(float temp, float hum, uint32_t seq, bool alert) {
  if (!telemetryEnabled()) return;
  const size_t length = ProtoWire::encodeTelemetry(messageBuffer, sizeof(messageBuffer),
                                                   SOURCE_ID, seq, temp, hum, millis(), alert);
  if (!length) {
    Serial.println("Erro: buffer Protobuf insuficiente");
    return;
  }
  if (telemetryUDP.beginPacket(gatewayIP, telemetryPort)) {
    telemetryUDP.write(messageBuffer, length);
    if (telemetryUDP.endPacket())
      Serial.printf("UDP Protobuf enviado seq=%lu bytes=%u alerta=%d\n",
                    static_cast<unsigned long>(seq), static_cast<unsigned>(length), alert);
  }
}
