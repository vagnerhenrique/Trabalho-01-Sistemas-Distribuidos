#pragma once
#include <Arduino.h>

// Fonte A controlavel: Gateway -> gRPC Bridge no PC -> UDP Protobuf -> ESP8266.
// O ESP8266 nao executa servidor gRPC nativo.
constexpr char SOURCE_ID[] = "FONTE_A";
constexpr bool SOURCE_CONTROLLABLE = true;
constexpr char SOURCE_KIND[] = "termohigrometro_ctrl";

// Fonte C - Sensor continuo nao controlavel
// constexpr char SOURCE_ID[] = "FONTE_C";
// constexpr bool SOURCE_CONTROLLABLE = false;
// constexpr char SOURCE_KIND[] = "termohigrometro_cont";

// OLED HW-364A: I2C diferente do NodeMCU comum.
constexpr uint8_t OLED_SDA_GPIO = 14; // D5
constexpr uint8_t OLED_SCL_GPIO = 12; // D6
constexpr uint8_t OLED_I2C_ADDR = 0x3C;
constexpr int16_t OLED_WIDTH = 128;
constexpr int16_t OLED_HEIGHT = 64;

constexpr uint8_t DHT_DATA_GPIO = 4;  // D2
constexpr uint32_t READ_INTERVAL_MS = 2500UL;
// Alternancia automatica entre leituras e informacoes da rede.
constexpr uint32_t OLED_PAGE_INTERVAL_MS = 5000UL;
// Quando a tela de rede esta ativa, atualiza a cada 1 segundo.
constexpr uint32_t OLED_NETWORK_REFRESH_MS = 1000UL;
constexpr uint32_t DEFAULT_SEND_INTERVAL_MS = 15000UL;
constexpr float DEFAULT_ALERT_TEMP_C = 30.0f;
constexpr uint16_t DISCOVERY_PORT = 50000;
constexpr uint16_t ANNOUNCE_PORT = 50001;
constexpr uint16_t TELEMETRY_PORT = 50002;
constexpr uint16_t CONTROL_PORT = 50031;
constexpr uint8_t MULTICAST_IP[4] = {239,255,42,99};
