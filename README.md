# Clean The CAM

Turns cncKad laser programs (Amada `.ENC`) into fast engraves.

cncKad's own hatch lifts the head between every stroke, which makes engraving
very slow. Clean The CAM rewrites the program so the engraving runs as a **fly
cut**: the beam is switched on once, the head stays down, and the control
switches the beam with the G0/G1 moves — no lift per stroke.

| In the file | What Clean The CAM does |
|---|---|
| **Fly-cut hatch** (ribbon Fly Cut) — tooled as *cut* contours, E1/E3… | every condition inside rewritten to the engrave condition (default E10), pierce set to A0 |
| **Stroke-by-stroke engraving** — `M103 … M104` per stroke | consecutive strokes joined into one fly cut |
| **Through-cuts** | never touched; if one was inheriting its condition from inside a rewritten block, its own condition is written back in front of it |

On the pomegranate samples that removes 298 head cycles from one file and 20
from the other; the old 3,532-stroke post loses 3,530.

## Using it

1. Run `CleanTheCAM.exe`
2. **Select .ENC file(s)** — pick one, or several for a batch
3. Check the options:
   - **Engrave condition** — default `E10`
   - **Home (G92)** — *Keep original* (cncKad's `X1250. Y1250.`), *Bottom left*
     (`X10. Y10.`, for the usual 10 mm of stock round the part) or *Custom*
   - **End position** — *Return home* (`G50`), *Back to start* (the G92 point:
     `G90 G00 X.. Y..` + `M30`) or *Custom*
4. **Run**. Look at the **Report** and the **Preview** tabs.
5. **Send to DNC** (single file, PASS only — asks first on warnings).

Output lands beside the original:

    <name>_clean.ENC
    <name>_clean_report.txt

The result is **PASS**, **PASS WITH WARNINGS** or **FAIL**. Nothing is written
on FAIL. Your choices are remembered between runs.

### Cleanup question

If the file contains junk the program can tidy, it asks before touching it:

- **zero-length moves / arcs** — some controls alarm on these; deleting them
  does not change the shape. (An arc with the same start and end but a real
  radius is a full circle and is never touched.)
- **lines engraved twice** — the second pass is skipped (deleted, or turned into
  a beam-off fly-over when the stroke continues), so the spot doesn't burn darker.

*Yes* cleans, *No* leaves the file as posted, *Cancel* skips the file.
Through-cuts are never cleaned.

## Safety checks

Every output is **parsed again from the written text and replayed** before it is
saved. The file is refused if any of these fail:

- every beam-on cutting move is identical to the original — same geometry, same
  order (minus only the moves you agreed to clean up)
- all engraving runs at the engrave condition and every through-cut keeps its own
- **no fly block after a through-cut** — in a fly cut the head stays down across
  the rapids and could catch a cut edge or a tipped slug; engraving must come first
- no Z motion inside a fly block
- the beam on/off structure is intact (no double M103, no stray M104)
- only absolute (G90) programs; exactly one G92 when the home is changed;
  recognised program ending
- the file has not already been through Clean The CAM (header stamp)

And it reports, as warnings:

- the beam-on rapid travel the joining added — total, and the longest single jump
- head-down rapids that leave the sheet (`(*SHEET ..)` with the `G98` offset)
- pierce dwell still active on engraving (when *force pierce to A0* is off)

The output header carries a stamp, e.g.
`(CLEAN THE CAM 1.0 - E10 A0 - 299 JOINED - 1 HATCH)` (kept as short as cncKad's
own comments), and the
`(JOB TIME ..)` comment is marked as cncKad's estimate *before* cleanup.

## Before cycle start

1. In a fly block the beam is commanded **on** across every G0 and the head stays
   down. That is only safe if the control inhibits the beam on rapids in fly-cut
   mode. cncKad's own hatch already relies on this, but the joined strokes jump
   in any direction — **prove it on scrap** before running a job.
2. Check the engrave condition's feed suits the fly-cut turnaround.
3. Dry-run or run on scrap first.

## Send to DNC

cncKad's simulator opens Metalix DNC as an automation server
(`DNC2000.exe -Embedding`) and calls `DNC.Document.LoadFile(path)`. **Send to
DNC** does exactly the same (single file, PASS only — asks first on warnings).
If that fails it opens DNC normally and puts the output path on the clipboard to
paste in. The ProgID, method and DNC location can be changed under **Settings**.

`tools/dnc_probe.py` lists the commands DNC accepts; `tools/dnc_test_load.py
FILE` performs one LoadFile by hand and waits, so you can watch what DNC does.

## Batch from the command line

    python CleanTheCAM.py --cli FOLDER_OR_FILES... [--home keep|bottom-left|X,Y]
        [--end home|start|X,Y] [--target E10] [--cleanup yes|no] [--dry-run]

Exit code 0 = all PASS, 1 = warnings, 2 = at least one FAIL. `_clean` files in
a folder are skipped.

## Building

Run `build_exe.bat` on a Windows machine with Python installed. It runs the tests
first and only builds if they pass. The result is `dist\CleanTheCAM.exe` — a
single file, no install needed.

To run without building: `python CleanTheCAM.py`

## Tests

    python -m pytest

`tests/samples` holds real cncKad posts and the hand-checked Etchify outputs; the
tests require Clean The CAM to reproduce their cutting sections line for line.
