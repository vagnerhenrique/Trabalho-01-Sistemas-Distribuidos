#pragma once

#include <Arduino.h>

namespace DisplayOLED {
  // Inicializa o OLED, retorna false caso nao responda via I2C.
  bool begin();
  void showStartup();
  void showReadings(float temperatureC, float humidityPercent, uint32_t sequence);
  void showSensorError();
  // Segunda tela: conexao Wi-Fi 2.4 GHz (modo STA), SSID, IP,
  // estado da descoberta do Gateway e intensidade do sinal.
  void showNetworkInfo(const String& ssid, const String& ip,
                       bool wifiConnected, bool gatewayDiscovered,
                       int32_t rssiDbm);
}
