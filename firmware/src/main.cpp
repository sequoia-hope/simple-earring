// simple_earring — "light drips" effect, two regions.
//
// Droplets of purple light spawn, slide downhill along the physical LED
// chains (gravity from the IMU), pool at the lowest point, and fade.
// Two independent drip regions:
//   - the perimeter outline (34 ring + 3 tip LEDs, a closed loop)
//   - the interior octagon (8 LEDs, an OPEN chain — 12.4mm gap at top)
// Motion feeds the rain: at rest a drip every ten-ish seconds; each
// walking step shakes a small burst into existence; sustained motion
// mixes in a little white. Physics runs in real millimeters (baked
// positions, local segment lengths), so drips move at the same physical
// speed everywhere. Brightness kept very low (worn-on-ear levels).
//
// POWER RHYTHM (Aug 25): the continuous pattern measured ~1h on a
// LIR2032 (~40mAh), i.e. ~40mA average. Three levers target 2x:
//   1. CPU at 50MHz instead of 150 (platformio.ini) — the awake MCU was
//      ~20mA of that budget.
//   2. The show plays in EPISODES with dark NAPS between: VLED hard-off
//      (45 idle SK6805 = ~13.5mA even showing black) and the IMU polled
//      slow. Worn/moving: ~12s show / ~8s nap (~60% LED duty). At rest
//      naps stretch to ~25s, so a still earring mostly sleeps. A hard
//      shake (well above walking-step jolts) ends a nap early.
//   3. The pattern itself is lazier: fewer spawns, slower slides.
// Future option if this isn't enough: IMU INT1 is wired to GP8, so a
// true dormant-until-motion rest mode is possible.
//
// CHARGING (CHRG or DONE low) preempts everything, instantly — no
// settling wait, no drip show, jostling irrelevant. A proportional arc
// of the perimeter ring blinks at the dimmest level: on one second, off
// four, repeat. Arc length is the percent; the colour is the tier:
//   red below 30%, orange 30-85%, green 85%+ (or DONE).
// The same indicator runs for two seconds at every power-on, charging
// or not, so switching on tells you where the battery stands.
//
// WEAR LOG: every power cycle opens a new LittleFS session file
// (/wNNNN.bin) and appends 10Hz motion-window records (gravity vector,
// jolt max/mean, motion envelope, VBATT). Protocol: switch on, stand
// 1 min, walk 1 min, dance 1 min, switch off — the session is then
// identifiable by shape and pullable over USB serial afterwards.
// Serial commands: L = list sessions, D<n> = dump CSV, X = wipe old.
// Records flush every 2s, so give it a beat before switching off.
//
// IMU->board transform calibrated Aug 25 (two-pose fit): mirror + 124deg
// (geometry: 180 - 56 footprint rot). Accel reads +1g on the UP axis,
// so down = -accel. Pin map: scripts/circuit.py @ ordered rev 43eadc1.

#include <Adafruit_NeoPixel.h>
#include <LittleFS.h>
#include <Wire.h>
#include <hardware/clocks.h>
#include <math.h>

#include "led_vecs.h"

constexpr uint8_t PIN_LED_EN = 1;
constexpr uint8_t PIN_LED_DATA = 18;
constexpr uint8_t PIN_IMU_SDA = 6;
constexpr uint8_t PIN_IMU_SCL = 11;
constexpr uint8_t PIN_CHRG = 19;
constexpr uint8_t PIN_DONE = 28;
constexpr uint8_t PIN_SW_SENSE = 29; // ADC3: SW_ON/2 via the 1M:1M divider
constexpr uint16_t N_LEDS = 45;

// Rev 2 power scheme: USB boots the chip even with SW2 off (VBUS feeds
// the LDO EN through a diode-OR). The sense divider's top is SW_ON, the
// switch common — so the one ADC reading encodes BOTH switch position
// and battery voltage:
//   > 1.27V          switch ON,  VBATT = 2x   (1M:1M divider; rev 1
//                    always reads here — its divider top is VBATT)
//   0.30 .. 1.27V    switch OFF, VBATT = 4x   (rev 2 WITH the 2M
//                    off-throw series mod: OFF selects VBATT via 2M,
//                    so the divider becomes VBATT/4 = 0.75-1.05V)
//   < 0.30V          switch OFF, VBATT unknown (rev 2 as first drawn:
//                    OFF throw hard-grounded)
// The bands cannot overlap: VBATT/2 >= 1.5V at the 3.0V cell floor,
// VBATT/4 <= 1.05V at the 4.2V ceiling.

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
constexpr int N_RING = 37; // perimeter loop = 100% of the level arc

// ---- activity tiers ----
// Calibrated from the Aug 25 wear log (worn on the ear: stand / walk /
// dance, ~50s each). The motion envelope separates all three with no
// overlap at all — standing 25-30, walking 84-159 (p10-p90), dancing
// 491-925 — so one filtered value drives the whole rhythm.
constexpr float MOTION_WALK = 50.0f;   // above: moving about
constexpr float MOTION_DANCE = 350.0f; // above: dancing
enum Activity : uint8_t { A_STILL, A_WALK, A_DANCE };

// ---- show/nap rhythm ----
// Nap length falls with activity: a still earring mostly sleeps, while
// walking (when people actually see it) gets only a short dark beat.
constexpr uint32_t EPISODE_MS = 12000;   // max continuous show before a nap
constexpr uint32_t NAP_STILL_MS = 25000; // still: sleep most of the time
constexpr uint32_t NAP_WALK_MS = 5000;   // walking: keep it seen
constexpr uint32_t NAP_DANCE_MS = 2000;  // dancing: barely pause
constexpr uint32_t DARK_NAP_MS = 3000;   // show dark+empty this long -> nap
constexpr uint32_t NAP_MIN_MS = 2000;    // no nap shorter than this
constexpr float SHAKE_WAKE = 450.0f;     // jolt_f: hard shake cuts a nap
// Step detect. Was 140, which caught only ~0.6 steps/s of real ~1.8/s
// walking in the wear log; walking jolt_max runs 66 (median) to 281
// (p90) while standing sits at 26 median / 35 p90, so 90 is still ~3x
// clear of the standing baseline.
constexpr float STEP_JOLT = 90.0f;

// ---- charge / level indicator ----
// A proportional arc of the perimeter ring steps up and back down in
// brightness over a second, then two seconds dark. The dark beat cuts
// VLED entirely (the 45 idle SK6805 draw ~13.5mA just sitting there) and
// hosts the VBATT measurement, so the average LED load stays a small
// slice of the ~41mA charge budget. Levels are RAW channel counts out of
// 255 with the brightness scaler disabled (see enterMode): NeoPixel's
// setBrightness multiplies by (b+1)>>8, which floors small counts to
// zero — the bug that made the old off-idle blip invisible.
constexpr uint32_t CHG_PERIOD_MS = 5000; // 1s lit + 4s dark
constexpr uint32_t CHG_PULSE_MS = 1000;
constexpr uint32_t BOOT_LEVEL_MS = 2000; // power-on battery-level splash
constexpr float CHG_RED_PCT = 30.0f;     // below this: red
constexpr float CHG_GREEN_PCT = 85.0f;   // at/above (or DONE): green
// Dimmest level that still renders all three tiers: orange is drawn at a
// 3:1 red:green ratio (green LEDs far outshine red at equal drive), so
// red needs 3 counts for green to land on 1. At 1 or 2, green floors to
// zero and orange would show as plain red.
constexpr uint8_t CHG_LEVEL = 3;

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
float last_az = 0; // board-frame az from the most recent sample, mg
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

struct Sense {
  bool on;      // slide switch position
  int vbatt_mv; // battery voltage, or -1 when the hardware can't say
};

static Sense senseOnce() {
  int mv = analogRead(PIN_SW_SENSE) * 3300 / 4095;
  if (mv > 1270) return {true, mv * 2};
  if (mv > 300) return {false, mv * 4};
  return {false, -1};
}

// debounced: 3 agreeing reads 5ms apart (the slide switch is
// break-before-make, so mid-flip the divider floats through C21's
// 75ms RC — a single read could catch the sag)
static Sense readSense() {
  Sense last = senseOnce();
  int agree = 1;
  for (int i = 1; i < 8; i++) {
    delay(5);
    Sense s = senseOnce();
    agree = (s.on == last.on) ? agree + 1 : 1;
    last = s;
    if (agree >= 3) return s;
  }
  return last;
}

// LIR2032 voltage -> rough charge percent. While the charger is pushing
// current the terminal voltage reads high (the cell's ~10R internal
// resistance at ~40mA lifts it ~0.15V), so subtract that first. This is
// a 5-segment-quality gauge, not a coulomb counter: the last ~25% of
// charge happens pinned at the 4.2V CV limit and reads the same.
static float chargePct(int mv, bool charging) {
  if (charging) mv -= 150;
  const int v[] = {3300, 3600, 3750, 3850, 3950, 4050, 4150, 4200};
  const float p[] = {0, 8, 25, 45, 62, 78, 92, 100};
  if (mv <= v[0]) return 0;
  for (int i = 1; i < 8; i++)
    if (mv <= v[i])
      return p[i - 1] +
             (p[i] - p[i - 1]) * (float)(mv - v[i - 1]) / (v[i] - v[i - 1]);
  return 100;
}

// ---- mode + rhythm state ----
enum RunMode : uint8_t { M_SHOW, M_OFF, M_CHARGE };
RunMode mode = M_SHOW;
uint32_t mode_entered_ms = 0;
bool sw_on = true;

bool napping = false, fading = false;
uint32_t episode_start_ms = 0, dark_since_ms = 0, fade_start_ms = 0;
uint32_t nap_start_ms = 0, nap_until_ms = 0;
bool rail_lit = false;     // charge/off modes: is VLED currently up?
bool pulse_active = false; // charge mode: mid-assembly (vs the dark beat)
float chg_pct = -1.0f;  // slewed gauge value; <0 = VBATT unreadable

// ---- wear log state ----
struct __attribute__((packed)) LogRec {
  uint32_t t_ms;
  int16_t fx, fy, az;           // mg: filtered in-plane gravity + raw az
  uint16_t jolt_max, jolt_mean; // mg, over the 100ms window
  uint16_t motion;              // slow envelope at record time
  uint16_t vbatt_mv;            // 0 when unreadable
  uint8_t flags;                // bit0 napping, bit1 step this window
  uint8_t rsvd;
};
File log_file;
char log_name[16];
bool log_ok = false;
uint32_t log_last_rec = 0, log_last_flush = 0, log_bytes = 0;
float log_jolt_max = 0, log_jolt_sum = 0;
int log_jolt_n = 0;
bool log_step = false;
// Two-speed logging: 10Hz for the first 3 minutes captures activity
// detail (the stand/walk/dance protocol fits here), then 1Hz carries a
// full battery run-down — 10Hz for hours would blow the partition
// (200 B/s = 720 KB/hour). Session time == time since boot, since each
// power cycle opens a new file; a board left charging for ages before
// being switched on gets the slow rate, which is the right call anyway.
constexpr uint32_t LOG_FAST_MS = 100;
constexpr uint32_t LOG_SLOW_MS = 1000;
constexpr uint32_t LOG_FAST_WINDOW_MS = 180000;
constexpr uint32_t LOG_MAX_BYTES = 300000; // 3min@10Hz + ~3.7h@1Hz
constexpr uint32_t LOG_KEEP_FREE = 81920;  // drop oldest sessions below this

// read the accel; update the gravity filter (fx,fy), the jolt/motion
// envelopes, and the wear-log window stats. Called at 50Hz during the
// show, ~20Hz while napping (the envelopes just move a bit slower in
// wall time there — thresholds are tuned for the show rate).
static void senseMotion() {
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
    last_az = az;
    jolt = fabsf(sqrtf(bx * bx + by * by + az * az) - 1000.0f);
  }
  jolt_f += (jolt > jolt_f ? 0.5f : 0.1f) * (jolt - jolt_f);
  motion += (jolt > motion ? 0.05f : 0.01f) * (jolt - motion);
  if (jolt > log_jolt_max) log_jolt_max = jolt;
  log_jolt_sum += jolt;
  log_jolt_n++;
}

// ---- wear log ----
static void logInit() {
  if (!LittleFS.begin()) {
    Serial.println("wearlog: no filesystem");
    return;
  }
  // rolling window: free space for this session by dropping the oldest
  FSInfo info;
  for (int guard = 0; guard < 32; guard++) {
    if (!LittleFS.info(info) ||
        info.totalBytes - info.usedBytes >= LOG_KEEP_FREE)
      break;
    Dir d = LittleFS.openDir("/");
    String oldest;
    while (d.next()) {
      String n = d.fileName();
      if (n.startsWith("w") && n.endsWith(".bin") &&
          (!oldest.length() || n < oldest))
        oldest = n;
    }
    if (!oldest.length()) break;
    LittleFS.remove("/" + oldest);
  }
  unsigned seq = 0, n = 0;
  Dir d = LittleFS.openDir("/");
  while (d.next())
    if (sscanf(d.fileName().c_str(), "w%u.bin", &n) == 1 && n >= seq)
      seq = n + 1;
  snprintf(log_name, sizeof(log_name), "/w%04u.bin", seq);
  log_file = LittleFS.open(log_name, "w");
  if (!log_file) {
    Serial.println("wearlog: open failed");
    return;
  }
  const uint8_t hdr[8] = {'E', 'A', 'R', 'w', 1, 0, sizeof(LogRec), 0};
  log_file.write(hdr, 8);
  log_ok = true;
  Serial.printf("wearlog: %s\n", log_name);
}

static void logTick() {
  if (!log_ok) return;
  uint32_t now = millis();
  uint32_t iv = now < LOG_FAST_WINDOW_MS ? LOG_FAST_MS : LOG_SLOW_MS;
  if (mode == M_SHOW && now - log_last_rec >= iv &&
      log_bytes < LOG_MAX_BYTES) {
    log_last_rec = now;
    LogRec r;
    r.t_ms = now;
    r.fx = (int16_t)fx;
    r.fy = (int16_t)fy;
    r.az = (int16_t)last_az;
    r.jolt_max = (uint16_t)fminf(log_jolt_max, 65535.0f);
    r.jolt_mean =
        (uint16_t)(log_jolt_n ? log_jolt_sum / (float)log_jolt_n : 0.0f);
    r.motion = (uint16_t)fminf(motion, 65535.0f);
    int mv = senseOnce().vbatt_mv;
    r.vbatt_mv = mv > 0 ? (uint16_t)mv : 0;
    r.flags = (napping ? 1 : 0) | (log_step ? 2 : 0);
    r.rsvd = 0;
    log_file.write((const uint8_t *)&r, sizeof(r));
    log_bytes += sizeof(r);
    log_jolt_max = log_jolt_sum = 0;
    log_jolt_n = 0;
    log_step = false;
  }
  // 2s flush window: a power-off loses at most the last 2s of records
  if (now - log_last_flush >= 2000) {
    log_last_flush = now;
    log_file.flush();
  }
}

static void handleCmd(const char *cmd) {
  if (cmd[0] == 'L') {
    Dir d = LittleFS.openDir("/");
    while (d.next())
      // record count, not a duration: the rate steps 10Hz -> 1Hz at 3
      // minutes, so only the timestamps in the dump give real elapsed time
      Serial.printf("%s  %u bytes  %u rec%s\n", d.fileName().c_str(),
                    (unsigned)d.fileSize(),
                    (unsigned)((d.fileSize() > 8 ? d.fileSize() - 8 : 0) /
                               sizeof(LogRec)),
                    (String("/") + d.fileName()) == log_name ? "  (live)"
                                                             : "");
  } else if (cmd[0] == 'D') {
    char name[16];
    snprintf(name, sizeof(name), "/w%04u.bin", (unsigned)atoi(cmd + 1));
    File f = LittleFS.open(name, "r");
    if (!f) {
      Serial.printf("no %s\n", name);
      return;
    }
    f.seek(8);
    Serial.println(
        "t_ms,fx_mg,fy_mg,az_mg,jolt_max,jolt_mean,motion,vbatt_mv,nap,step");
    LogRec r;
    while (f.read((uint8_t *)&r, sizeof(r)) == sizeof(r))
      Serial.printf("%lu,%d,%d,%d,%u,%u,%u,%u,%u,%u\n",
                    (unsigned long)r.t_ms, r.fx, r.fy, r.az, r.jolt_max,
                    r.jolt_mean, r.motion, r.vbatt_mv, r.flags & 1,
                    (r.flags >> 1) & 1);
    f.close();
    Serial.println("end");
  } else if (cmd[0] == 'X') {
    int wiped = 0;
    bool again = true;
    while (again) { // delete-while-iterating is dicey: restart each pass
      again = false;
      Dir d = LittleFS.openDir("/");
      while (d.next()) {
        String nm = "/" + d.fileName();
        if (nm != log_name && nm.startsWith("/w") && nm.endsWith(".bin")) {
          LittleFS.remove(nm);
          wiped++;
          again = true;
          break;
        }
      }
    }
    Serial.printf("wiped %d old sessions\n", wiped);
  }
}

static void pollSerial() {
  static char buf[16];
  static uint8_t len = 0;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      buf[len] = 0;
      if (len) handleCmd(buf);
      len = 0;
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = c;
    }
  }
}

// ---- show mode: drip episodes with dark naps between ----
static Activity activity() {
  if (motion > MOTION_DANCE) return A_DANCE;
  if (motion > MOTION_WALK) return A_WALK;
  return A_STILL;
}

static uint32_t napLength() {
  switch (activity()) {
    case A_DANCE: return NAP_DANCE_MS;
    case A_WALK: return NAP_WALK_MS;
    default: return NAP_STILL_MS;
  }
}

static void startNap(uint32_t dur) {
  napping = true;
  fading = false;
  nap_start_ms = millis();
  nap_until_ms = nap_start_ms + dur;
  strip.clear();
  strip.show();
  digitalWrite(PIN_LED_EN, LOW); // rail off: the whole point of the nap
  n_drops = 0;
  for (int i = 0; i < N_LEDS; i++) ledv[i] = 0;
  Serial.printf("nap %lus (motion=%d)\n", (unsigned long)(dur / 1000),
                (int)motion);
}

static void wakeShow() {
  napping = false;
  digitalWrite(PIN_LED_EN, HIGH);
  delay(10); // VLED settle before first frame
  strip.clear();
  strip.show();
  episode_start_ms = millis();
  dark_since_ms = 0;
}

static void runShowFrame() {
  constexpr float DT = 0.02f;
  static uint32_t last_status = 0, last_step = 0;
  uint32_t now = millis();

  senseMotion();

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

  // ---- spawn: lazy trickle at rest, a small burst per step ----
  // (halved from the 1h-battery tune; no spawns while fading to a nap)
  if (!fading) {
    bool step = jolt_f > STEP_JOLT && (now - last_step) > 400;
    if (step) {
      last_step = now;
      log_step = true;
      int n = 1 + (int)(rp2040.hwrand32() % 2);
      for (int k = 0; k < n; k++) spawnDrop();
    }
    float p_spawn = 0.002f + fminf(motion / 350.0f, 1.0f) * 0.025f;
    if ((rp2040.hwrand32() & 0xFFFF) < (uint32_t)(p_spawn * 65536))
      spawnDrop();
  }

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
        float speed_mm = 10.0f + 40.0f * fminf(fabsf(grade), 1.0f);
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
    if (fading) dr.inten *= 0.93f;      // episode ending: drain fast
    if (!have_down) dr.inten *= 0.99f;  // face-flat: gently evaporate
  }
  for (int d = n_drops - 1; d >= 0; d--)
    if (drops[d].inten < 0.04f) drops[d] = drops[--n_drops];

  // ---- render: stamp kernels into a decaying buffer (fading tails) ----
  for (int i = 0; i < N_LEDS; i++) ledv[i] *= fading ? 0.78f : 0.86f;
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
    const char *act = activity() == A_DANCE   ? "dance"
                      : activity() == A_WALK  ? "walk"
                                              : "still";
    Serial.printf("drops=%d jolt=%d motion=%d(%s) down_ang=%d sat=%u "
                  "vbatt=%dmV chrg=%d done=%d ep=%lus log=%luB\n",
                  n_drops, (int)jolt_f, (int)motion, act,
                  (int)(atan2f(dy, dx) * 180.0f / (float)M_PI), sat,
                  // same sense as measureCharge's line: 1 = asserted
                  senseOnce().vbatt_mv, digitalRead(PIN_CHRG) == LOW,
                  digitalRead(PIN_DONE) == LOW,
                  (unsigned long)((now - episode_start_ms) / 1000),
                  (unsigned long)log_bytes);
  }
  delay(20);
}

static void runShowNap() {
  uint32_t now = millis();
  if (napping) {
    senseMotion(); // keep gravity + envelopes warm for the wake
    // start moving during a long rest nap and the nap shortens to match
    // — otherwise walking off mid-nap leaves you dark for 25s
    uint32_t want_end = nap_start_ms + napLength();
    if (want_end < nap_until_ms) nap_until_ms = want_end;
    if (now >= nap_until_ms ||
        (jolt_f > SHAKE_WAKE && now - nap_start_ms > NAP_MIN_MS))
      wakeShow();
    else
      delay(50);
    return;
  }
  runShowFrame();
  // ---- rhythm bookkeeping ----
  float vmax = 0;
  for (int i = 0; i < N_LEDS; i++) vmax = fmaxf(vmax, ledv[i]);
  bool dark = n_drops == 0 && vmax < 0.02f;
  uint32_t nap_len = napLength();
  if (fading) {
    if (dark || now - fade_start_ms > 1500) startNap(nap_len);
  } else if (now - episode_start_ms > EPISODE_MS) {
    fading = true; // graceful fade-out, then nap
    fade_start_ms = now;
  } else {
    if (!dark) dark_since_ms = 0;
    else if (!dark_since_ms) dark_since_ms = now;
    if (dark_since_ms && now - dark_since_ms > DARK_NAP_MS)
      startNap(nap_len);
  }
}

// ---- the level indicator (charging and at power-on) ----
// TWO readings at once, on the perimeter ring only:
//   how MANY LEDs  = charge percent (proportional arc of the 37-LED ring)
//   what COLOUR    = red below 30%, orange 30-85%, green 85%+ or DONE
// The arc simply blinks: on at the dimmest level for a second, off for
// four, repeat. No fade, no ramp, no dither — at these counts every
// smoother option either bands or shimmers, and a plain blink reads
// cleanly on a piece this small. The 4s dark also drops the average LED
// load to a fifth, leaving more of the ~41mA charge budget for the cell.
//
// Honest limitation (unchanged): the LGS4056H terminates on total
// BAT-pin current (C/10 = ~4mA) and the awake MCU draws more than that
// from the same node, so DONE cannot assert while this firmware runs;
// green therefore comes from the voltage estimate, which itself
// saturates in the CV phase. Treat green as "nearly there".
int arc_n = 0;

// one solid colour per level, scaled to the current ramp step
static uint32_t levelColor(float pct, bool known, uint8_t s) {
  if (!known) return strip.Color(0, 0, s); // powered, but VBATT unreadable
  if (pct >= CHG_GREEN_PCT) return strip.Color(0, s, 0);
  if (pct >= CHG_RED_PCT) return strip.Color(s, s / 3, 0); // 3:1 = orange
  return strip.Color(s, 0, 0);
}

static int arcLength(float pct, bool known) {
  if (!known) return 3; // short stub: "powered, level unknown"
  int n = (int)lroundf(pct / 100.0f * N_RING);
  if (n < 2) n = 2; // a flat cell must still SHOW as charging, not go dark
  if (n > N_RING) n = N_RING;
  return n;
}

// Paint the arc once; the pixels then latch for the rest of the second.
static void showArc() {
  bool known = chg_pct >= 0;
  arc_n = arcLength(chg_pct, known);
  uint32_t col = levelColor(chg_pct, known, CHG_LEVEL);
  strip.clear();
  for (int i = 0; i < arc_n; i++) strip.setPixelColor(i, col);
  strip.show();
}

static void railOn() {
  if (!rail_lit) {
    digitalWrite(PIN_LED_EN, HIGH);
    delay(3);
    rail_lit = true;
  }
}

static void railOff() {
  if (rail_lit) {
    strip.clear();
    strip.show();
    digitalWrite(PIN_LED_EN, LOW);
    rail_lit = false;
  }
}

// Take a reading now. Kept separate from the frame loop so power-on can
// call it before anything slow (IMU, filesystem) and light up immediately
// — the old code waited up to a second for its first measurement.
static void measureCharge() {
  bool chg = digitalRead(PIN_CHRG) == LOW;
  bool done = digitalRead(PIN_DONE) == LOW;
  Sense s = readSense();
  if (done)
    chg_pct = 100.0f;
  else if (s.vbatt_mv > 0) {
    float p = chargePct(s.vbatt_mv, chg);
    chg_pct = chg_pct < 0 ? p : chg_pct + 0.3f * (p - chg_pct);
  } else
    chg_pct = -1.0f; // switch off without the off-throw mod: nothing to read
  Serial.printf("level chrg=%d done=%d vbatt=%dmV pct=%d\n", chg, done,
                s.vbatt_mv, (int)chg_pct);
}

static void runChargeFrame() {
  uint32_t ph = (millis() - mode_entered_ms) % CHG_PERIOD_MS;
  if (ph < CHG_PULSE_MS) {
    if (!pulse_active) { // leading edge: light it once and let it latch
      pulse_active = true;
      railOn();
      showArc();
    }
  } else if (pulse_active) {
    // Falling edge, once per cycle: rail down first, THEN measure — no
    // LED load on the cell while sampling, and readSense's debounce
    // delays land in the dark where they cannot hitch the blink.
    pulse_active = false;
    railOff();
    measureCharge(); // the reading the next blink will show
  }
  delay(10);
}

// ---- power-on splash: battery level for two seconds, charging or not ----
// Blocking on purpose, and called before IMU/filesystem init so it is the
// first thing that happens after the rail comes up.
static void bootLevelSplash() {
  strip.setBrightness(255); // raw counts, scaler off: see CHG_LEVEL
  railOn();
  showArc();
  delay(BOOT_LEVEL_MS);
  railOff();
}

// ---- off-idle: switch OFF, USB keeping the LDO up, charger idle ----
// (no cell fitted, or the charger latched off). A faint blip every 5s
// says "powered but switched off"; rail off between.
static void runIdleFrame() {
  uint32_t ph = (millis() - mode_entered_ms) % 5000;
  if (ph < 700) {
    railOn();
    strip.clear();
    for (int i = 34; i <= 36; i++)
      strip.setPixelColor(i, strip.Color(0, 0, CHG_LEVEL));
    strip.show();
  } else {
    railOff();
  }
  delay(50);
}

static void enterMode(RunMode m) {
  mode = m;
  mode_entered_ms = millis();
  napping = false;
  fading = false;
  rail_lit = false;
  n_drops = 0;
  for (int i = 0; i < N_LEDS; i++) ledv[i] = 0;
  // Indicator modes run on RAW channel counts (brightness scaler off, see
  // CHG_LEVEL); only the drip show uses the scaler. Entering charge mode
  // measures straight away so the first pulse already carries a reading.
  strip.setBrightness(m == M_SHOW ? GLOBAL_BRIGHTNESS : 255);
  pulse_active = false;
  if (m == M_CHARGE) {
    chg_pct = -1.0f; // fresh reading, not slewed off the last mode's value
    measureCharge();
  }
  strip.clear();
  // charge/idle raise the rail per-pulse themselves; only the show
  // holds it up continuously
  digitalWrite(PIN_LED_EN, m == M_SHOW ? HIGH : LOW);
  if (m == M_SHOW) delay(10); // VLED settle before first frame
  strip.show();
  episode_start_ms = mode_entered_ms;
  dark_since_ms = 0;
  Serial.printf("mode -> %s\n", m == M_SHOW    ? "show"
                                : m == M_CHARGE ? "charge"
                                                : "off-idle");
}

// The sense divider is 1M:1M with C21 = 100nF on the bottom leg, so
// VBSENSE rises with tau = 500k * 100nF = 50ms — and at power-on C21
// starts EMPTY. Sampling before it settles reads a FRACTION of the true
// voltage: a 4.0V cell (68%) decodes as 0-4% anywhere in the 60-100ms
// window, and below ~55ms VBSENSE is still under the 1.27V band edge, so
// even the switch position decodes wrong. 8 tau puts the residual under
// 0.1%. millis() already counts from core start and C21 began charging
// before that, so this credits the boot time that has passed.
constexpr uint32_t BOOT_SETTLE_MS = 400;

// 500k source impedance is far above what the RP2350 ADC's sample-and-
// hold wants; its first conversions after init read low until the S/H
// cap has been charged a few times. Throw those away.
static void adcWarmup() {
  for (int i = 0; i < 8; i++) {
    analogRead(PIN_SW_SENSE);
    delay(1);
  }
}

void setup() {
  // Ordered for a fast first reading: pins, LEDs, measure, splash — and
  // only THEN the slow parts (IMU probe, LittleFS mount, which can take
  // hundreds of ms and formats on a fresh chip). The battery level is on
  // screen within ~50ms of power-on rather than after all of that.
  pinMode(PIN_CHRG, INPUT_PULLUP);
  pinMode(PIN_DONE, INPUT_PULLUP);
  analogReadResolution(12);
  Serial.begin(115200);

  pinMode(PIN_LED_EN, OUTPUT);
  digitalWrite(PIN_LED_EN, LOW);
  strip.begin();

  adcWarmup();
  int mv_early = analogRead(PIN_SW_SENSE) * 3300 / 4095;
  uint32_t t_early = millis();
  while (millis() < BOOT_SETTLE_MS) delay(5); // let C21 finish charging
  int mv_settled = analogRead(PIN_SW_SENSE) * 3300 / 4095;
  Serial.printf("boot sense: %dmV @%lums -> %dmV @%lums (C21 tau=50ms)\n",
                mv_early, (unsigned long)t_early, mv_settled,
                (unsigned long)millis());

  measureCharge();
  bootLevelSplash(); // two seconds of level, charging or not

  Wire1.setSDA(PIN_IMU_SDA);
  Wire1.setSCL(PIN_IMU_SCL);
  Wire1.begin();
  Wire1.setClock(400000);
  uint8_t who = 0;
  imu_ok = imuRead(REG_WHO_AM_I, &who, 1) && who == 0x6A;
  if (imu_ok) imu_ok = imuWrite(REG_CTRL1_XL, 0x40); // 104 Hz, +-2 g

  logInit();
  // clk_sys is the battery lever — print it so a silently-ignored
  // f_cpu build flag can't masquerade as a disappointing runtime
  Serial.printf("boot: clk_sys=%luMHz imu=%s\n",
                (unsigned long)(clock_get_hz(clk_sys) / 1000000),
                imu_ok ? "ok" : "FAIL");

  sw_on = readSense().on;
  bool charger =
      digitalRead(PIN_CHRG) == LOW || digitalRead(PIN_DONE) == LOW;
  enterMode(charger ? M_CHARGE : (sw_on ? M_SHOW : M_OFF));
}

void loop() {
  static uint32_t last_sw = 0;
  uint32_t now = millis();
  pollSerial();
  // charger pins checked EVERY pass: plugging in flips to the charge
  // indicator within one frame, from any mode, moving or not
  bool charger =
      digitalRead(PIN_CHRG) == LOW || digitalRead(PIN_DONE) == LOW;
  RunMode want;
  if (charger) {
    want = M_CHARGE;
  } else {
    if (mode == M_CHARGE || now - last_sw >= 500) { // 2Hz switch poll
      last_sw = now;
      sw_on = readSense().on;
    }
    want = sw_on ? M_SHOW : M_OFF;
  }
  if (want != mode) enterMode(want);
  logTick();
  switch (mode) {
    case M_CHARGE: runChargeFrame(); break;
    case M_OFF: runIdleFrame(); break;
    default: runShowNap(); break;
  }
}
