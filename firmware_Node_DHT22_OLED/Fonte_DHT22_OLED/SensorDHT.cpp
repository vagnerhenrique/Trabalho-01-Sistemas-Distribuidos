#include "SensorDHT.h"

#include <Arduino.h>
#include <DHT.h>
#include <math.h>

#include "Config.h"

namespace {
  DHT dht(DHT_DATA_GPIO, DHT22); // DHT22 = AM2302
}

void SensorDHT::begin() {
  dht.begin();
}

bool SensorDHT::read(SensorReading &out) {
  const float humidity = dht.readHumidity();
  const float temperature = dht.readTemperature();

  if (isnan(humidity) || isnan(temperature)) {
    return false;
  }

  out.temperatureC = temperature;
  out.humidityPercent = humidity;
  return true;
}
