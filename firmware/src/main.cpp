// simple_earring staged bring-up smoke test.
//
// Brings hardware up one stage at a time, narrating on USB CDC (115200),
// so a crash/brownout names its culprit via the last line printed:
//   t=0   USB CDC only (LED power explicitly OFF)
//   t=3s  I2C1 + LSM6DS3TR-C WHO_AM_I
//   t=6s  VLED on, single dim LED
//   t=9s  full 45-LED rainbow (low brightness)
//   t=12s first BOOTSEL read (suspends XIP briefly — tested last)
// Steady state: rainbow + 1 Hz status line.
//
// Pin map source of truth: scripts/circuit.py @ ordered rev 43eadc1.

#include <Adafruit_NeoPixel.h>
#include <Wire.h>

constexpr uint8_t PIN_LED_EN = 1;    // TPS22913 EN, R10 pulls low at boot
constexpr uint8_t PIN_LED_DATA = 18; // LED_D0 -> LED1.DI
constexpr uint8_t PIN_IMU_SDA = 6;   // I2C1
constexpr uint8_t PIN_IMU_SCL = 11;  // I2C1
constexpr uint8_t PIN_CHRG = 19;     // low = charging
constexpr uint8_t PIN_DONE = 28;     // low = charge complete
constexpr uint16_t N_LEDS = 45;      // 34 ring + 3 tip + 8 interior

constexpr uint8_t IMU_ADDR = 0x6A;   // SA0 -> GND
constexpr uint8_t REG_WHO_AM_I = 0x0F; // expect 0x6A
constexpr uint8_t REG_CTRL1_XL = 0x10;
constexpr uint8_t REG_OUTX_L_XL = 0x28;

Adafruit_NeoPixel strip(N_LEDS, PIN_LED_DATA, NEO_GRB + NEO_KHZ800);
int stage = 0;
bool imu_ok = false;
bool bootsel_ok = false;

static bool imuWrite(uint8_t reg, uint8_t val) {
  Wire1.beginTransmission(IMU_ADDR);
  Wire1.write(reg);
  Wire1.write(val);
  return Wire1.endTransmission() == 0;
}

static bool imuRead(uint8_t reg, uint8_t *buf, size_t n) {
  Wire1.beginTransmission(IMU_ADDR);
  Wire1.write(reg);
  if (Wire1.endTransmission(false) != 0) return false;
  if (Wire1.requestFrom(IMU_ADDR, n) != n) return false;
  for (size_t i = 0; i < n; i++) buf[i] = Wire1.read();
  return true;
}

void setup() {
  pinMode(PIN_LED_EN, OUTPUT);
  digitalWrite(PIN_LED_EN, LOW); // VLED stays off until stage 2
  pinMode(PIN_CHRG, INPUT_PULLUP);
  pinMode(PIN_DONE, INPUT_PULLUP);
  Serial.begin(115200);
}

void loop() {
  static uint32_t last_beat = 0;
  static uint16_t phase = 0;
  uint32_t now = millis();

  if (stage == 0 && now >= 3000) {
    stage = 1;
    Serial.println("[stage 1] I2C1 + IMU init...");
    Wire1.setSDA(PIN_IMU_SDA);
    Wire1.setSCL(PIN_IMU_SCL);
    Wire1.begin();
    Wire1.setClock(400000);
    uint8_t who = 0;
    imu_ok = imuRead(REG_WHO_AM_I, &who, 1) && who == 0x6A;
    if (imu_ok) imu_ok = imuWrite(REG_CTRL1_XL, 0x40); // 104 Hz, +-2 g
    Serial.printf("[stage 1] IMU WHO_AM_I=0x%02X -> %s\n", who,
                  imu_ok ? "OK" : "FAIL");
  }
  if (stage == 1 && now >= 6000) {
    stage = 2;
    Serial.println("[stage 2] VLED on, one dim LED...");
    digitalWrite(PIN_LED_EN, HIGH);
    delay(10);
    strip.begin();
    strip.setBrightness(5);
    strip.clear();
    strip.setPixelColor(0, strip.Color(0, 255, 0));
    strip.show();
    Serial.println("[stage 2] done");
  }
  if (stage == 2 && now >= 9000) {
    stage = 3;
    Serial.println("[stage 3] full rainbow, brightness 10...");
    strip.setBrightness(10);
    Serial.println("[stage 3] done");
  }
  if (stage == 3 && now >= 12000) {
    stage = 4;
    Serial.println("[stage 4] first BOOTSEL read (XIP suspend)...");
    bootsel_ok = true;
    bool b = BOOTSEL;
    Serial.printf("[stage 4] BOOTSEL=%d ok — all stages up\n", (int)b);
  }

  if (stage >= 3) {
    for (uint16_t i = 0; i < N_LEDS; i++)
      strip.setPixelColor(
          i, strip.ColorHSV((phase + i * (65536 / N_LEDS)) & 0xFFFF));
    phase += 256;
    strip.show();
  }

  if (now - last_beat >= (stage >= 4 ? 1000 : 500)) {
    last_beat = now;
    Serial.printf("up=%lums stage=%d imu=%s chrg=%s done=%s",
                  (unsigned long)now, stage, imu_ok ? "OK" : "-",
                  digitalRead(PIN_CHRG) ? "no" : "CHARGING",
                  digitalRead(PIN_DONE) ? "no" : "DONE");
    if (imu_ok) {
      uint8_t raw[6];
      if (imuRead(REG_OUTX_L_XL, raw, 6)) {
        int16_t ax = raw[0] | (raw[1] << 8);
        int16_t ay = raw[2] | (raw[3] << 8);
        int16_t az = raw[4] | (raw[5] << 8);
        Serial.printf(" accel[mg]=%d,%d,%d", (int)(ax * 0.061f),
                      (int)(ay * 0.061f), (int)(az * 0.061f));
      }
    }
    if (bootsel_ok) Serial.printf(" bootsel=%d", (int)BOOTSEL);
    Serial.println();
  }
  delay(30);
}
