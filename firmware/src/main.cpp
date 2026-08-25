// simple_earring — "light drips" effect, two regions.
//
// Droplets of purple light spawn, slide downhill along the physical LED
// chains (gravity from the IMU), pool at the lowest point, and fade.
// Two independent drip regions:
//   - the perimeter outline (34 ring + 3 tip LEDs, a closed loop)
//   - the interior octagon (8 LEDs, an OPEN chain — 12.4mm gap at top)
// Motion feeds the rain: at rest a drip every few seconds; each walking
// step shakes a small burst into existence; sustained motion mixes in a
// little white. Physics runs in real millimeters (baked positions, local
// segment lengths), so drips move at the same physical speed everywhere.
// Brightness kept very low (worn-on-ear levels).
//
// IMU->board transform calibrated Aug 25 (two-pose fit): mirror + 124deg
// (geometry: 180 - 56 footprint rot). Accel reads +1g on the UP axis,
// so down = -accel. Pin map: scripts/circuit.py @ ordered rev 43eadc1.

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

constexpr bool IMU_FLIP_X = true;
constexpr bool IMU_FLIP_Z = true;
constexpr float IMU_COS = -0.559193f; // cos(124deg)
constexpr float IMU_SIN = 0.829038f;  // sin(124deg)

constexpr uint16_t HUE_PURPLE = 49152;
constexpr uint8_t GLOBAL_BRIGHTNESS = 8;

struct Region {
  int start, n;
  bool closed;
  float kern;   // render kernel half-width, index units
  int krange;
};
constexpr Region REGS[2] = {
    {0, 37, true, 1.7f, 2},  // perimeter loop
    {37, 8, false, 0.6f, 1}, // interior octagon (open chain)
};
constexpr int INTERIOR_SPAWN_PCT = 25;

constexpr int MAX_DROPS = 12;
struct Drop {
  float pos;   // fractional index within its region
  float inten; // 0..1
  uint8_t reg;
  bool pooled;
};
Drop drops[MAX_DROPS];
int n_drops = 0;

Adafruit_NeoPixel strip(N_LEDS, PIN_LED_DATA, NEO_GRB + NEO_KHZ800);
bool imu_ok = false;
float fx, fy;
float jolt_f = 0, motion = 0;
float ledv[N_LEDS];
float hbuf[N_LEDS];
float hmin[2], hmax[2];

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

// region-local index -> absolute LED index (closed: wraps; open: clamps)
static inline int regIdx(const Region &R, int i) {
  if (R.closed) return R.start + ((i % R.n) + R.n) % R.n;
  return R.start + (i < 0 ? 0 : (i >= R.n ? R.n - 1 : i));
}

static void pointAt(const Region &R, float p, float &x, float &y) {
  if (!R.closed) p = fmaxf(0.0f, fminf(p, (float)(R.n - 1)));
  int i0 = (int)floorf(p);
  float f = p - i0;
  int a = regIdx(R, i0), b = regIdx(R, i0 + 1);
  x = LED_X[a] + (LED_X[b] - LED_X[a]) * f;
  y = LED_Y[a] + (LED_Y[b] - LED_Y[a]) * f;
}

static float heightAt(const Region &R, float p, float dx, float dy) {
  float x, y;
  pointAt(R, p, x, y);
  return -(x * dx + y * dy); // mm above the floor direction
}

static void spawnDrop() {
  if (n_drops >= MAX_DROPS) return;
  uint8_t rg = (rp2040.hwrand32() % 100) < INTERIOR_SPAWN_PCT ? 1 : 0;
  const Region &R = REGS[rg];
  int idx = 0;
  for (int t = 0; t < 6; t++) { // land in the upper part of the region
    idx = rp2040.hwrand32() % R.n;
    if (hbuf[R.start + idx] > hmin[rg] + 0.35f * (hmax[rg] - hmin[rg]))
      break;
  }
  drops[n_drops++] = {(float)idx, 1.0f, rg, false};
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
  strip.setBrightness(GLOBAL_BRIGHTNESS);
  strip.show();
}

void loop() {
  constexpr float DT = 0.02f;
  static uint32_t last_status = 0, last_step = 0;
  uint32_t now = millis();

  // ---- sense ----
  uint8_t raw[6];
  float jolt = 0;
  if (imu_ok && imuRead(REG_OUTX_L_XL, raw, 6)) {
    float ax = (int16_t)(raw[0] | (raw[1] << 8)) * 0.061f;
    float ay = (int16_t)(raw[2] | (raw[3] << 8)) * 0.061f;
    float az = (int16_t)(raw[4] | (raw[5] << 8)) * 0.061f;
    if (IMU_FLIP_X) ax = -ax;
    if (IMU_FLIP_Z) az = -az;
    float bx = ax * IMU_COS - ay * IMU_SIN;
    float by = ax * IMU_SIN + ay * IMU_COS;
    fx += 0.2f * (bx - fx);
    fy += 0.2f * (by - fy);
    jolt = fabsf(sqrtf(bx * bx + by * by + az * az) - 1000.0f);
  }
  jolt_f += (jolt > jolt_f ? 0.5f : 0.1f) * (jolt - jolt_f);
  motion += (jolt > motion ? 0.05f : 0.01f) * (jolt - motion);

  // ---- gravity direction / per-region heights ----
  float gxy = sqrtf(fx * fx + fy * fy);
  bool have_down = gxy > 100.0f;
  float dx = 0, dy = -1;
  if (have_down) { dx = -fx / gxy; dy = -fy / gxy; } // down = -accel
  for (int r = 0; r < 2; r++) {
    hmin[r] = 1e9f;
    hmax[r] = -1e9f;
    for (int i = REGS[r].start; i < REGS[r].start + REGS[r].n; i++) {
      hbuf[i] = -(LED_X[i] * dx + LED_Y[i] * dy);
      hmin[r] = fminf(hmin[r], hbuf[i]);
      hmax[r] = fmaxf(hmax[r], hbuf[i]);
    }
  }

  // ---- spawn: quiet trickle at rest, a burst per step ----
  bool step = jolt_f > 140.0f && (now - last_step) > 320;
  if (step) {
    last_step = now;
    int n = 2 + (int)(rp2040.hwrand32() % 3);
    for (int k = 0; k < n; k++) spawnDrop();
  }
  float p_spawn = 0.004f + fminf(motion / 350.0f, 1.0f) * 0.05f;
  if ((rp2040.hwrand32() & 0xFFFF) < (uint32_t)(p_spawn * 65536))
    spawnDrop();

  // ---- physics: slide downhill in real mm, pool at the bottom, fade ----
  for (int d = 0; d < n_drops; d++) {
    Drop &dr = drops[d];
    const Region &R = REGS[dr.reg];
    if (have_down && !dr.pooled) {
      float hf = heightAt(R, dr.pos + 0.5f, dx, dy);
      float hb = heightAt(R, dr.pos - 0.5f, dx, dy);
      float x0, y0, x1, y1;
      pointAt(R, dr.pos - 0.5f, x0, y0);
      pointAt(R, dr.pos + 0.5f, x1, y1);
      float seg = fmaxf(hypotf(x1 - x0, y1 - y0), 0.5f); // mm per index
      float grade = (hf - hb) / seg;                     // dimensionless
      float h = heightAt(R, dr.pos, dx, dy);
      bool at_end = !R.closed &&
                    ((dr.pos <= 0.01f && grade > 0) ||
                     (dr.pos >= R.n - 1.01f && grade < 0));
      if (h < hmin[dr.reg] + 0.9f || fabsf(grade) < 0.05f || at_end) {
        dr.pooled = true;
      } else {
        float speed_mm = 13.0f + 60.0f * fminf(fabsf(grade), 1.0f);
        dr.pos += (grade < 0 ? 1.0f : -1.0f) * (speed_mm / seg) * DT;
        if (R.closed) {
          if (dr.pos >= R.n) dr.pos -= R.n;
          if (dr.pos < 0) dr.pos += R.n;
        } else {
          dr.pos = fmaxf(0.0f, fminf(dr.pos, (float)(R.n - 1)));
        }
      }
    }
    dr.inten *= dr.pooled ? 0.955f : 0.999f;
    if (!have_down) dr.inten *= 0.99f; // face-flat: gently evaporate
  }
  for (int d = n_drops - 1; d >= 0; d--)
    if (drops[d].inten < 0.04f) drops[d] = drops[--n_drops];

  // ---- render: stamp kernels into a decaying buffer (fading tails) ----
  for (int i = 0; i < N_LEDS; i++) ledv[i] *= 0.86f;
  for (int d = 0; d < n_drops; d++) {
    const Region &R = REGS[drops[d].reg];
    int c = (int)floorf(drops[d].pos);
    for (int k = -R.krange; k <= R.krange; k++) {
      if (!R.closed && (c + k < 0 || c + k >= R.n)) continue;
      int idx = regIdx(R, c + k);
      float w = 1.0f - fabsf((float)(c + k) - drops[d].pos) / R.kern;
      if (w > 0) {
        float v = drops[d].inten * w * w;
        if (v > ledv[idx]) ledv[idx] = v;
      }
    }
  }
  uint8_t sat = 255;
  if (motion > 100.0f) // sustained motion mixes in a little white
    sat = 255 - (uint8_t)(fminf((motion - 100.0f) / 300.0f, 1.0f) * 70.0f);
  for (int i = 0; i < N_LEDS; i++) {
    float v = fminf(ledv[i], 1.0f);
    strip.setPixelColor(i, strip.ColorHSV(HUE_PURPLE, sat,
                                          (uint8_t)(v * 255.0f)));
  }
  strip.show();

  if (now - last_status >= 1000) {
    last_status = now;
    Serial.printf("drops=%d jolt=%d motion=%d down_ang=%d sat=%u chrg=%s\n",
                  n_drops, (int)jolt_f, (int)motion,
                  (int)(atan2f(dy, dx) * 180.0f / (float)M_PI), sat,
                  digitalRead(PIN_CHRG) ? "no" : "CHARGING");
  }
  delay(20);
}
