# Avatar Lab, Generation 8 (Glass)

The live page is the Avatar Lab artifact (claude.ai/artifact/A3PWLpJuTdQ5mb9X3gMV4C); `avatar-lab.html` here is its
source (generations 5-8). `sheets.js` renders a contact sheet per avatar (each state as 3 frames, three moods, three
moments, and the chat size): `node sheets.js 8.1` from this folder writes `sheets/sheet-8.1.png`. Render one code per run:
the page draws only the avatars named, and with more than one or two it drops below 20 fps, where the clock (capped at
0.05 s a frame) falls behind real time, so motion between frames shrinks and mood colors are caught mid-fade. Rounds 1
to 6 were recorded at about 7 fps, all avatars drawing at once.

## How Gen 8 is graded

A separate grader (a fresh model with no access to the code) scores each contact sheet against the Gen 7.2 sheet and
the owner's inspiration images, on: frontier look 25, depth 15, state reactions 25, moods and moments 15, small size
10, craft 10. Pass is 90. Hard rule from the owner: everything must read as light; anything that reads as polygons,
outlines, wire or beads caps "frontier look" at 70. On this scale the approved Gen 7.2 scores about 80.

| Round | 8.1 Ribbons | 8.2 Horizon | 8.3 Aurora | 8.4 Prism / Liquid | 8.5 Plasma | 8.6 Nebula |
|---|---|---|---|---|---|---|
| 1 | 65.0 | 62.4 | 53.5 | 57.9 (Prism) | 65.2 | 55.3 |
| 2 | 70.8 | 72.0 | 67.7 | 65.5 (Liquid) | 67.9 | 70.5 |
| 3 | 78.5 | 76.9 | 70.9 | 67.5 | 71.9 | 72.1 |
| 4 | 80.5 | 77.0 | 68.5 | 69.3 | 73.2 | 71.1 |
| 5 | 81.7 | 80.1 | 68.6 (dropped) | 71.5 | 76.3 | 71.1 |
| 6 | 73.0 | 72.5 | (dropped) | 66.0 | 69.5 | 61.5 |

Round 6 came from a new, harsher grader: asked to score the Gen 7.2 reference on the same rubric, it gave 67.5 (earlier
graders put 7.2 at about 80), so its scale runs about 12 points lower. Against the reference, Ribbons went from +1.7 in
round 5 to +5.5 and Horizon from about 0 to +5. Its main asks: Ribbons' listening reads as an eye; Horizon's speaking
zig-zag reads as cracked glass; the cores are hard white dots; moods (concerned, sleepy) both read magenta; the glass
needs a Fresnel rim; alert needs a pulse inside, not just a rim tint.

Saved for later (in the lab's "Saved for later" shelf, code kept): 8.3 Aurora (dropped after round 5: sleepy and
speaking kept reading as cut-out fins) and 8.7 Prism (dropped after round 1: read as flat polygons).

What moved scores most: drawing everything as glow (soft sprites, layered falloff, a bloom pass, an inner haze) instead
of fills and lines; one distinct silhouette per state; capped exposure (no flat white cores); continuous halos (never
dotted or stroked rings). What the grader still wants: no hard white edge anywhere, visible motion in every state, and
bolder light at chat size.

None is in the app yet: none has passed 90. Ribbons and Horizon already match or beat Gen 7.
