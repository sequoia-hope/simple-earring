// simple_earring — accelerometer-reactive display.
//
// The LED ring becomes a physics instrument:
//   - a bright arc always points at the floor (in-plane gravity),
//   - hue tracks out-of-plane tilt (face-up magenta ... face-down cyan),
//   - shaking flashes the whole ring brighter and whiter.
//
// The IMU->board mapping (back-side mount, rotated) is tunable live over
// USB CDC so the transform can be calibrated without reflashing:
//   'x' toggle in-plane X flip     'z' toggle Z flip
//   'o'/'p' rotate offset -/+ 5 degrees
//   current mapping is echoed in every status line; bake the final
//   values into IMU_* defaults below.
//
// Pin map source of truth: scripts/circuit.py @ ordered rev 43eadc1.

#include <Adafruit_NeoPixel.h>
#include <Wire.h>
#include <math.h>

#include "led_vecs.h"

constexpr uint8_t PIN_LED_EN = 1;
constexpr uint8_t PIN_LED_DATA = 18;
constexpr uint8_t PIN_IMU_SDA = 6;
constexpr uint8_t PIN_IMU_SCL = 11;
constexpr uint8_t PIN_CHRG = 19;
constexpr uint8_t PIN_DONE = 28;
constexpr uint16_t N_LEDS = 45;

constexpr uint8_t IMU_ADDR = 0x6A;
constexpr uint8_t REG_WHO_AM_I = 0x0F;
constexpr uint8_t REG_CTRL1_XL = 0x10;
constexpr uint8_t REG_OUTX_L_XL = 0x28;

// IMU -> board-front-view transform. Calibrated Aug 25 from two hand-held
// poses (tip-up, tip-right): mirror + rotation, measured 120.6 deg +-3;
// geometry predicts 180 - 56 (footprint rot) = 124 deg, within noise.
bool imu_flip_x = true;   // back-side mount mirrors one in-plane axis
bool imu_flip_z = true;   // package top faces away from the viewer
float imu_rot_deg = 124.0f;

Adafruit_NeoPixel strip(N_LEDS, PIN_LED_DATA, NEO_GRB + NEO_KHZ800);
bool imu_ok = false;
float fx, fy, fz;      // filtered accel, board frame, mg
float shake = 0;       // filtered |mag - 1g| energy, mg

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
  pinMode(PIN_CHRG, INPUT_PULLUP);
  pinMode(PIN_DONE, INPUT_PULLUP);
  Serial.begin(115200);

  Wire1.setSDA(PIN_IMU_SDA);
  Wire1.setSCL(PIN_IMU_SCL);
  Wire1.begin();
  Wire1.setClock(400000);
  uint8_t who = 0;
  imu_ok = imuRead(REG_WHO_AM_I, &who, 1) && who == 0x6A;
  if (imu_ok) imu_ok = imuWrite(REG_CTRL1_XL, 0x40); // 104 Hz, +-2 g

  pinMode(PIN_LED_EN, OUTPUT);
  digitalWrite(PIN_LED_EN, HIGH);
  delay(10);
  strip.begin();
  strip.setBrightness(30); // global cap keeps the coin cell honest
  strip.show();
}

void loop() {
  static uint32_t last_status = 0;

  while (Serial.available()) {
    switch (Serial.read()) {
      case 'x': imu_flip_x = !imu_flip_x; break;
      case 'z': imu_flip_z = !imu_flip_z; break;
      case 'o': imu_rot_deg -= 5; break;
      case 'p': imu_rot_deg += 5; break;
    }
  }

  uint8_t raw[6];
  if (imu_ok && imuRead(REG_OUTX_L_XL, raw, 6)) {
    float ax = (int16_t)(raw[0] | (raw[1] << 8)) * 0.061f;
    float ay = (int16_t)(raw[2] | (raw[3] << 8)) * 0.061f;
    float az = (int16_t)(raw[4] | (raw[5] << 8)) * 0.061f;
    if (imu_flip_x) ax = -ax;
    if (imu_flip_z) az = -az;
    float cr = cosf(imu_rot_deg * (float)M_PI / 180.0f);
    float sr = sinf(imu_rot_deg * (float)M_PI / 180.0f);
    float bx = ax * cr - ay * sr;
    float by = ax * sr + ay * cr;

    fx += 0.25f * (bx - fx);
    fy += 0.25f * (by - fy);
    fz += 0.25f * (az - fz);
    float mag = sqrtf(bx * bx + by * by + az * az);
    float jolt = fabsf(mag - 1000.0f);
    shake += (jolt > shake ? 0.5f : 0.05f) * (jolt - shake);
  }

  // in-plane "down" direction (unit), degenerate when face-flat
  float gxy = sqrtf(fx * fx + fy * fy);
  float dx = 0, dy = -1;
  if (gxy > 100.0f) { dx = fx / gxy; dy = fy / gxy; }
  float plane = fminf(gxy / 1000.0f, 1.0f); // arc contrast fades face-flat

  // hue from out-of-plane tilt, distinct endpoints:
  // face-down red (0) -> on-edge green -> face-up blue (43690)
  float t = fminf(fmaxf((fz + 1000.0f) / 2000.0f, 0.0f), 1.0f);
  uint16_t hue = (uint16_t)(t * 43690.0f);
  float sh = fminf(shake / 400.0f, 1.0f); // 0..1 shake energy
  uint8_t sat = 255 - (uint8_t)(sh * 200);  // shake whitens

  for (uint16_t i = 0; i < N_LEDS; i++) {
    float align = LED_UX[i] * dx + LED_UY[i] * dy; // 1 = pointing at floor
    float a3 = align > 0 ? align * align * align : 0;
    float v = 40 + plane * a3 * 170 + sh * 120;
    strip.setPixelColor(i, strip.ColorHSV(hue, sat,
                                          (uint8_t)fminf(v, 255.0f)));
  }
  strip.show();

  uint32_t now = millis();
  if (now - last_status >= 1000) {
    last_status = now;
    Serial.printf("accel[mg]=%d,%d,%d down_ang=%d shake=%d hue=%u "
                  "map[x=%d z=%d rot=%d] chrg=%s\n",
                  (int)fx, (int)fy, (int)fz,
                  (int)(atan2f(dy, dx) * 180.0f / (float)M_PI), (int)shake,
                  hue, (int)imu_flip_x, (int)imu_flip_z, (int)imu_rot_deg,
                  digitalRead(PIN_CHRG) ? "no" : "CHARGING");
  }
  delay(20);
}
