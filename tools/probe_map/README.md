# probe_map — annotated multimeter probe guide (out/probe/)

Generates out/probe/index.html: ordered-rev board renders with numbered
probe-point overlays for USB bring-up debugging. Run from a scratch dir:

1. Extract the rev the physical board was built from:
   `git show <rev>:out/earring.kicad_pcb > ordered/out/earring.kicad_pcb`
   and symlink `ordered/library -> <repo>/library` (3D models resolve via
   `${KIPRJMOD}/../library`).
2. `python3 dump_geom.py ordered/out/earring.kicad_pcb > geom.json`
   (pcbnew; pads + footprints + outline for the nets/refs of interest)
3. `kicad-cli pcb render --side top|bottom --quality high --zoom 0.92
   -w 1400 -h 1640 -o probe_{top,bottom}.png ordered/out/earring.kicad_pcb`
4. `python3 calibrate.py` — fits mm->px (orthographic render; board edge
   found at alpha>200: the raytrace has a wide low-alpha glow that fools
   lower thresholds). Writes cal.json + verify_*.png overlay check.
5. `python3 gen_probe.py` — writes out/probe/ (page, overlays, closeups).

Calibration for the 43eadc1 renders: 40.584 px/mm, board x-center at
px 687, board y=115.248mm at px 1537; bottom view mirrors x.
