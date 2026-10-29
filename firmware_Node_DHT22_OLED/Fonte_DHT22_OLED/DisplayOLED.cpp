#include "DisplayOLED.h"

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include "Config.h"

namespace {
  Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, -1);

  void header() {
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.print(F("TRAB 01 | "));
    display.print(SOURCE_ID);
    display.drawFastHLine(0, 10, OLED_WIDTH, SSD1306_WHITE);
  }
}

bool DisplayOLED::begin() {
  // HW-364A: SDA = GPIO14 (D5); SCL = GPIO12 (D6).
  Wire.begin(OLED_SDA_GPIO, OLED_SCL_GPIO);
  Wire.setClock(100000UL);

  // Verifica se ha um dispositivo respondendo no endereco esperado.
  Wire.beginTransmission(OLED_I2C_ADDR);
  if (Wire.endTransmission() != 0) {
    return false;
  }

  // periphBegin=false impede que Adafruit_SSD1306 reconfigure o I2C
  // para os pinos padrao do NodeMCU, perdendo o mapeamento HW-364A.
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDR, true, false)) {
    return false;
  }

  display.clearDisplay();
  display.display();
  return true;
}

void DisplayOLED::showStartup() {
  display.clearDisplay();
  header();
  display.setCursor(0, 22);
  display.println(F("Iniciando sensor"));
  display.println(F("DHT22 / AM2302"));
  display.display();
}

void DisplayOLED::showReadings(float temperatureC,
                               float humidityPercent,
                               uint32_t sequence) {
  display.clearDisplay();
  header();

  display.setTextSize(2);
  display.setCursor(0, 16);
  display.print(F("T:"));
  display.print(temperatureC, 1);
  display.print(F(" C"));

  display.setCursor(0, 35);
  display.print(F("UR:"));
  display.print(humidityPercent, 1);
  display.print(F("%"));

  display.drawFastHLine(0, 54, OLED_WIDTH, SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 56);
  display.print(F("Leituras: "));
  display.print(sequence);
  display.display();
}

void DisplayOLED::showSensorError() {
  display.clearDisplay();
  header();
  display.setCursor(0, 21);
  display.println(F("Falha no DHT22"));
  display.setCursor(0, 38);
  display.println(F("Verifique fios"));
  display.println(F("e alimentacao"));
  display.display();
}

void DisplayOLED::showNetworkInfo(const String& ssid, const String& ip,
                                  bool wifiConnected, bool gatewayDiscovered,
                                  int32_t rssiDbm) {
  display.clearDisplay();
  header();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);

  display.setCursor(0, 16);
  display.print(F("WiFi: "));
  display.print(wifiConnected ? F("CONECTADO") : F("SEM CONEXAO"));

  // display.setCursor(0, 23);
  // display.print(F("Tipo: WiFi STA 2.4G"));

  display.setCursor(0, 30);
  display.print(F("SSID: "));
  // 128px = 21 caracteres no tamanho 1; cabem 15 apos "SSID: ".
  display.print(ssid.substring(0, 15));

  display.setCursor(0, 43);
  display.print(F("IP: "));
  display.print(ip);

  display.setCursor(0, 53);
  if (!wifiConnected) {
    display.print(F("GW: SEM REDE"));
  } else {
    display.print(gatewayDiscovered ? F("GW: OK ") : F("GW: AGUARDANDO"));
    if (gatewayDiscovered) {
      display.print(rssiDbm);
      display.print(F("dBm"));
    }
  }
  display.display();
}
