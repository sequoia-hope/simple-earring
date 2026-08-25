// simple_earring — "light drips" effect.
//
// Droplets of purple light spawn on the perimeter, slide downhill along
// the physical outline (gravity from the IMU), pool at the bottom-most
// point, and fade out. Motion feeds the rain: at rest a drip appears
// every few seconds; each walking step shakes a small burst of drops
// into existence, and sustained motion mixes a little white in.
// Brightness is kept very low throughout (worn-on-ear levels).
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
constexpr float IMU_ROT_DEG = 124.0f;

constexpr uint16_t HUE_PURPLE = 49152;  // between blue and magenta
constexpr uint8_t GLOBAL_BRIGHTNESS = 8; // very low — jewelry, not a torch

constexpr int MAX_DROPS = 12;
struct Drop {
  float pos;    // fractional perimeter index, 0..N_PERIM
  float inten;  // 0..1
  bool pooled;
};
Drop drops[MAX_DROPS];
int n_drops = 0;

Adafruit_NeoPixel strip(N_LEDS, PIN_LED_DATA, NEO_GRB + NEO_KHZ800);
bool imu_ok = false;
float fx, fy;          // filtered in-plane accel, board frame, mg
float jolt_f = 0;      // fast |mag-1g| (step impacts)
float motion = 0;      // slow motion energy
float ledv[N_LEDS];    // persistence buffer (gives drips a fading tail)
float hbuf[N_PERIM];   // per-perimeter-LED height this frame

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

static inline int wrapP(int i) {
  return ((i % N_PERIM) + N_PERIM) % N_PERIM;
}

static float heightAt(float p, float dx, float dy) {
  int i0 = (int)floorf(p);
  float f = p - i0;
  int a = wrapP(i0), b = wrapP(i0 + 1);
  float x = LED_X[a] + (LED_X[b] - LED_X[a]) * f;
  float y = LED_Y[a] + (LED_Y[b] - LED_Y[a]) * f;
  return -(x * dx + y * dy); // mm above the floor direction
}

static void spawnDrop(float hmin, float hmax) {
  if (n_drops >= MAX_DROPS) return;
  // land in the upper part of the outline so there is somewhere to drip to
  int idx = rp2040.hwrand32() % N_PERIM;
  for (int t = 0; t < 6; t++) {
    idx = rp2040.hwrand32() % N_PERIM;
    if (hbuf[idx] > hmin + 0.35f * (hmax - hmin)) break;
  }
  drops[n_drops++] = {(float)idx, 1.0f, false};
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
    constexpr float CR = -0.559193f; // cos(124deg)
    constexpr float SR = 0.829038f;  // sin(124deg)
    float bx = ax * CR - ay * SR;
    float by = ax * SR + ay * CR;
    fx += 0.2f * (bx - fx);
    fy += 0.2f * (by - fy);
    jolt = fabsf(sqrtf(bx * bx + by * by + az * az) - 1000.0f);
  }
  jolt_f += (jolt > jolt_f ? 0.5f : 0.1f) * (jolt - jolt_f);
  motion += (jolt > motion ? 0.05f : 0.01f) * (jolt - motion);

  // ---- gravity direction / heights ----
  float gxy = sqrtf(fx * fx + fy * fy);
  bool have_down = gxy > 100.0f;
  float dx = 0, dy = -1;
  if (have_down) { dx = -fx / gxy; dy = -fy / gxy; } // down = -accel
  float hmin = 1e9f, hmax = -1e9f;
  for (int i = 0; i < N_PERIM; i++) {
    hbuf[i] = -(LED_X[i] * dx + LED_Y[i] * dy);
    hmin = fminf(hmin, hbuf[i]);
    hmax = fmaxf(hmax, hbuf[i]);
  }

  // ---- spawn: quiet trickle at rest, a burst per step ----
  bool step = jolt_f > 140.0f && (now - last_step) > 320;
  if (step) {
    last_step = now;
    int n = 2 + (int)(rp2040.hwrand32() % 3);
    for (int k = 0; k < n; k++) spawnDrop(hmin, hmax);
  }
  float p_spawn = 0.004f + fminf(motion / 350.0f, 1.0f) * 0.05f; // per frame
  if ((rp2040.hwrand32() & 0xFFFF) < (uint32_t)(p_spawn * 65536))
    spawnDrop(hmin, hmax);

  // ---- physics: slide downhill, pool at the bottom, fade ----
  for (int d = 0; d < n_drops; d++) {
    Drop &dr = drops[d];
    if (have_down && !dr.pooled) {
      float hf = heightAt(dr.pos + 0.5f, dx, dy);
      float hb = heightAt(dr.pos - 0.5f, dx, dy);
      float slope = hf - hb; // mm per index
      float h = heightAt(dr.pos, dx, dy);
      if (h < hmin + 0.9f || fabsf(slope) < 0.12f) {
        dr.pooled = true;
      } else {
        float speed = 5.0f + 22.0f * fminf(fabsf(slope) / 1.5f, 1.0f);
        dr.pos += (slope < 0 ? 1.0f : -1.0f) * speed * DT;
        if (dr.pos >= N_PERIM) dr.pos -= N_PERIM;
        if (dr.pos < 0) dr.pos += N_PERIM;
      }
    }
    dr.inten *= dr.pooled ? 0.955f : 0.999f; // pooled: fade out ~1s
    if (!have_down) dr.inten *= 0.99f;       // face-flat: gently evaporate
  }
  for (int d = n_drops - 1; d >= 0; d--)     // compact away dead drops
    if (drops[d].inten < 0.04f) drops[d] = drops[--n_drops];

  // ---- render: stamp kernels into a decaying buffer (fading tails) ----
  for (int i = 0; i < N_LEDS; i++) ledv[i] *= 0.86f;
  for (int d = 0; d < n_drops; d++) {
    int c = (int)floorf(drops[d].pos);
    for (int k = -2; k <= 2; k++) {
      int idx = wrapP(c + k);
      float dist = fabsf((float)(c + k) - drops[d].pos);
      float w = 1.0f - dist / 1.7f;
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
