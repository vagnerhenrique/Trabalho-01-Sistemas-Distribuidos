#pragma once

struct SensorReading {
  float temperatureC;
  float humidityPercent;
};

namespace SensorDHT {
  void begin();
  // Retorna false quando a leitura nao e valida.
  bool read(SensorReading &out);
}
