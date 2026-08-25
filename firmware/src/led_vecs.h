// LED positions in mm, board front view, origin = board center,
// +X right, +Y toward the USB tip. Index = strip position = LED{i+1}.
// 0..36 form the closed perimeter loop (34 ring + 3 tip chevron);
// 37..44 are the interior octagon.
#pragma once
constexpr int N_LEDS_TAB = 45;
constexpr int N_PERIM = 37;
constexpr float LED_X[N_LEDS_TAB] = {
       -4.62f,    -5.94f,    -7.25f,    -8.91f,   -10.57f,   -11.82f,
      -12.70f,   -13.17f,   -13.21f,   -12.82f,   -12.01f,   -10.80f,
       -9.24f,    -7.38f,    -5.28f,    -3.00f,    -0.63f,    +1.77f,
       +4.11f,    +6.31f,    +8.31f,   +10.03f,   +11.43f,   +12.45f,
      +13.06f,   +13.25f,   +13.00f,   +12.33f,   +11.25f,    +9.93f,
       +8.60f,    +7.28f,    +5.95f,    +4.62f,    +2.45f,    +0.00f,
       -2.45f,    -6.20f,    -9.30f,    -6.00f,    -2.20f,    +2.20f,
       +6.00f,    +9.30f,    +6.20f,
};
constexpr float LED_Y[N_LEDS_TAB] = {
      +17.00f,   +15.02f,   +13.04f,   +10.54f,    +8.04f,    +6.00f,
       +3.77f,    +1.42f,    -0.98f,    -3.34f,    -5.60f,    -7.67f,
       -9.49f,   -11.00f,   -12.15f,   -12.91f,   -13.24f,   -13.13f,
      -12.60f,   -11.65f,   -10.32f,    -8.66f,    -6.71f,    -4.54f,
       -2.22f,    +0.17f,    +2.55f,    +4.85f,    +6.99f,    +9.00f,
      +11.00f,   +13.00f,   +15.00f,   +17.00f,   +17.85f,   +18.60f,
      +17.85f,    +6.80f,    +0.50f,    -7.60f,    -9.30f,    -9.30f,
       -7.60f,    +0.50f,    +6.80f,
};
