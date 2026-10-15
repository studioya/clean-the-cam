import os

import pytest

from clean_the_cam import core
from clean_the_cam.core import Options, process

HERE = os.path.dirname(__file__)
SAMPLES = os.path.join(HERE, 'samples')


def sample(name):
    return os.path.join(SAMPLES, name)


def read(name):
    with open(sample(name), newline='') as f:
        return f.read()


def body(text):
    """Everything up to and including the last M104 - the cutting section."""
    lines = text.splitlines()
    last = max(n for n, l in enumerate(lines) if l.startswith('M104'))
    return lines[:last + 1]


# a minimal program in cncKad's shape -------------------------------------------

HEAD = """%
O7000 (TEST)
(PART SIZE: 20. X 20. )
(*SHEET 40. 40. 1.0)
(MAT Stainless 1.0)
M102 (C-SUS1.0)
G92 X1250. Y1250.
M100
G90
G98X10.Y10.
"""
TAIL = """(JOB TIME 00:10 )
G50
%
"""
CUT = """E5
G0X0.Y0.
M103
G1X20.
Y20.
X0.
Y0.
M104 Z60.
"""
STROKES = """E10
G0X1.Y1.
M103A0
G1X5.Y1.
M104
G0X1.Y2.
M103A0
G1X5.Y2.
M104
G0X1.Y3.
M103A0
G1X5.Y3.
M104 Z60.
"""
HATCH = """E1
G0X2.Y5.
M103
G1X8.Y5.
G0X12.Y5.
G1X18.Y5.
E3
G0X18.Y6.
G1X2.Y6.
M104
"""


def prog(*parts):
    return HEAD + ''.join(parts) + TAIL


# --- reference outputs ---------------------------------------------------------

@pytest.mark.parametrize('src,ref', [
    ('pomegranate_nohatch.ENC', 'pomegranate_nohatch_etchified.ENC'),
    ('pomegranate.ENC', 'pomegranate_etchified.ENC'),
])
def test_reproduces_reference_cutting_section(src, ref):
    r = process(sample(src), Options(stamp=False, cleanup=False))
    assert r.ok, r.errors
    assert body(r.text) == body(read(ref))


def test_pomegranate_numbers():
    r = process(sample('pomegranate.ENC'), Options(cleanup=False))
    st = r.stats
    assert st['joined_strokes'] == 21
    assert st['gates_removed'] == 20
    assert st['hatch_blocks'] == 1
    assert st['retargeted'] == {'E1': 2, 'E3': 1}
    assert st['reemitted'] == [(2529, 'E1')]
    assert st['rapid_on_added_moves'] == 20
    assert round(st['rapid_on_added'], 1) == 61.5


def test_nohatch_numbers():
    r = process(sample('pomegranate_nohatch.ENC'), Options(cleanup=False))
    assert r.stats['gates_removed'] == 298
    assert r.stats['rapid_on_added_moves'] == 298


def test_line_endings_preserved():
    r = process(sample('pomegranate.ENC'), Options(cleanup=False))
    assert r.text.count('\r\n') == len(r.text.splitlines())
    assert r.text.endswith('%\r\n')


def test_lf_and_no_final_newline_preserved():
    text = prog(STROKES, CUT).rstrip('\n')
    r = process(text, Options())
    assert r.ok, r.errors
    assert '\r' not in r.text
    assert not r.text.endswith('\n')


# --- home / ending / stamp -----------------------------------------------------

def test_home_bottom_left_and_return_to_start():
    r = process(prog(STROKES, CUT), Options(home='bottom_left', end='start'))
    assert r.ok, r.errors
    lines = r.text.splitlines()
    assert 'G92 X10. Y10.' in lines
    assert lines[-3:] == ['G90 G00 X10. Y10.', 'M30', '%']
    assert '(JOB TIME 00:10 - CNCKAD ESTIMATE BEFORE CLEANUP)' in lines


def test_keep_home_and_return_home_g50():
    r = process(prog(STROKES, CUT), Options(home='keep', end='home'))
    lines = r.text.splitlines()
    assert 'G92 X1250. Y1250.' in lines
    assert lines[-2:] == ['G50', '%']


def test_custom_home_and_end():
    r = process(prog(STROKES, CUT), Options(home='custom', home_xy=('15', '12.5'),
                                            end='custom', end_xy=(100, 200)))
    lines = r.text.splitlines()
    assert 'G92 X15. Y12.5' in lines
    assert lines[-3:-1] == ['G90 G00 X100. Y200.', 'M30']


def test_custom_needs_numbers():
    r = process(prog(STROKES, CUT), Options(home='custom', home_xy=('abc', '')))
    assert r.status == 'FAIL'


def test_stamp_after_program_number():
    r = process(prog(STROKES, CUT), Options(home='bottom_left'))
    lines = r.text.splitlines()
    assert lines[1] == 'O7000 (TEST)'
    assert lines[2].startswith('(CLEAN THE CAM')
    assert 'HOME X10. Y10.' in lines[2]


def test_already_processed_is_refused():
    r = process(prog(STROKES, CUT), Options())
    again = process(r.text, Options())
    assert again.status == 'FAIL'
    assert 'already' in again.errors[0]


def test_unknown_ending_is_refused():
    text = prog(STROKES, CUT).replace('G50', 'M99')
    assert process(text, Options()).status == 'FAIL'


# --- the transform -------------------------------------------------------------

def test_strokes_joined_and_hatch_retargeted():
    r = process(prog(STROKES, HATCH, CUT), Options())
    assert r.ok, r.errors
    lines = r.text.splitlines()
    # strokes: one gate
    assert r.stats['gates_removed'] == 2
    # hatch: E1/E3 -> E10, pierce A0
    assert 'E1' not in lines and 'E3' not in lines
    assert lines.count('M103A0') == 2
    assert lines.count('M103') == 1          # the through-cut keeps its own pierce
    # the cut keeps E5
    assert 'E5' in lines


def test_inherited_condition_reemitted():
    # the cut has no E of its own: it inherits E3 from inside the hatch
    cut_no_e = CUT.replace('E5\n', '')
    r = process(prog(STROKES, HATCH, cut_no_e), Options())
    assert r.ok, r.errors
    lines = r.text.splitlines()
    k = lines.index('G0X0.Y0.')
    assert lines[k - 1] == 'E3' and lines[k - 2] == 'M104'
    assert r.stats['reemitted']


def test_hatch_sharing_condition_line_gets_its_own():
    # E1 is set once before a through-cut and reused by the hatch after it ->
    # the shared line must not be rewritten (that would change the cut)
    text = prog(STROKES, """E1
G0X0.Y0.
M103
G1X1.
Y1.
M104
G0X2.Y5.
M103
G1X8.Y5.
G0X12.Y5.
G1X18.Y5.
M104
""")
    r = process(text, Options())
    # hatch after a through-cut is a safety failure anyway
    assert r.status == 'FAIL'
    assert any('AFTER a through-cut' in e for e in r.errors)


def test_fly_block_after_through_cut_is_refused():
    r = process(prog(CUT.replace('M104 Z60.', 'M104'), STROKES), Options())
    assert r.status == 'FAIL'
    assert any('AFTER a through-cut' in e for e in r.errors)
    assert r.text == ''


def test_strokes_after_cut_without_joining_are_fine():
    # a single stroke after a cut is not a fly block - head lifts as normal
    one = """E10
G0X1.Y1.
M103A0
G1X5.Y1.
M104 Z60.
"""
    r = process(prog(CUT, one), Options())
    assert r.ok, r.errors


def test_no_join_across_z_retract():
    two = STROKES.replace('G1X5.Y1.\nM104\n', 'G1X5.Y1.\nM104 Z60.\n')
    r = process(prog(two, CUT), Options())
    assert r.stats['gates_removed'] == 1


def test_unbalanced_beam_is_refused():
    text = prog(STROKES, CUT).replace('M104 Z60.\nE5', 'E5', 1)
    r = process(text, Options())
    assert r.status == 'FAIL'


def test_z_inside_cutting_section_is_refused():
    text = prog(STROKES.replace('G1X5.Y2.', 'G1X5.Y2.Z3.'), CUT)
    r = process(text, Options())
    assert r.status == 'FAIL'
    assert 'Z motion' in r.errors[0]


def test_incremental_is_refused():
    r = process(prog(STROKES, CUT).replace('G90\n', 'G91\n'), Options())
    assert r.status == 'FAIL'


def test_bad_target():
    assert process(prog(STROKES, CUT), Options(target='10')).status == 'FAIL'


def test_offsheet_rapid_warns():
    far = STROKES.replace('G0X1.Y2.', 'G0X-15.Y2.')
    r = process(prog(far, CUT), Options())
    assert r.ok
    assert any('leave the' in w for w in r.warnings)


# --- cleanup -------------------------------------------------------------------

JUNK = """E10
G0X1.Y1.
M103A0
G1X5.Y1.
X5.Y1.
X5.Y4.
X5.Y1.
X9.Y1.
M104
G0X1.Y8.
M103A0
G1X5.Y8.
G2X5.Y8.I0.J0.
G3X5.Y8.I1.J0.
M104 Z60.
"""


def test_cleanup_asks_first():
    r = process(prog(JUNK, CUT), Options())
    assert r.status == 'DECIDE'
    kinds = sorted(c['what'] for c in r.cleanup)
    assert kinds == ['line engraved twice', 'zero-length arc', 'zero-length move']
    assert 'zero-length' in core.describe_cleanup(r)


def test_cleanup_declined_leaves_moves():
    r = process(prog(JUNK, CUT), Options(cleanup=False))
    assert r.ok, r.errors
    assert 'X5.Y1.' in r.text.splitlines()


def test_cleanup_applied_and_verified():
    r = process(prog(JUNK, CUT), Options(cleanup=True))
    assert r.ok, r.errors
    lines = r.text.splitlines()
    # the retrace back to X5 Y1 became a fly-over, the next cut re-asserts G1
    k = lines.index('G0X5.Y1.')
    assert lines[k + 1] == 'G1X9.Y1.'
    # zero-length arc gone, the full circle (radius 1) kept
    assert 'G2X5.Y8.I0.J0.' not in lines
    assert 'G3X5.Y8.I1.J0.' in lines
    assert len(r.stats['cleanup_removed']) == 3


def test_cleanup_never_touches_through_cuts():
    cut = CUT.replace('Y20.\n', 'Y20.\nY20.\n')
    r = process(prog(STROKES, cut), Options())
    assert r.status != 'DECIDE'
    assert 'Y20.' in r.text


def test_gcode_sample_with_cleanup():
    r = process(sample('pomegranate_gcode.ENC'), Options(home='bottom_left', cleanup=True))
    assert r.ok, r.errors
    assert r.stats['cleanup_removed']
    assert r.stats['gates_removed'] == 3530


# --- the verifier itself ---------------------------------------------------------

def test_verifier_catches_a_missing_cut():
    text = prog(STROKES, CUT)
    lines = [core.Line(t, n + 1) for n, t in enumerate(text.splitlines())]
    moves, spans, _ = core.replay(lines)
    core._classify(spans, 'E10')
    tampered = text.replace('G1X5.Y2.\n', 'G1X5.Y2.5\n')
    r = core.Result()
    info = dict(sheet=(40, 40), g98=(10, 10))
    core._verify(tampered, moves, spans, set(), 'E10', info, True, r)
    assert any('verification failed' in e for e in r.errors)


def test_verifier_catches_wrong_condition():
    text = prog(STROKES, CUT)
    lines = [core.Line(t, n + 1) for n, t in enumerate(text.splitlines())]
    moves, spans, _ = core.replay(lines)
    core._classify(spans, 'E10')
    tampered = text.replace('E5\n', 'E10\n')
    r = core.Result()
    core._verify(tampered, moves, spans, set(), 'E10', dict(), True, r)
    assert any('through-cut' in e for e in r.errors)


def test_report_renders_for_every_status():
    for opts in (Options(), Options(cleanup=True)):
        r = process(prog(JUNK, CUT), opts)
        assert 'CLEAN THE CAM' in core.format_report('a.ENC', 'b.ENC', r)
    r = process('not a program\n', Options())
    assert r.status == 'FAIL'
    assert 'FAIL' in core.format_report('a', 'b', r)
