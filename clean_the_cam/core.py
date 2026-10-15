"""
Clean The CAM - transform engine.

Takes an Amada .ENC posted by cncKad and turns its engraving into fast fly-cut
engraving:

  * fly-cut hatch    cncKad's ribbon Fly Cut tools the hatch as CUT contours
                     (E1, E3 ...). Every condition inside it is rewritten to the
                     engrave condition and the pierce dwell is set to A0.
  * stroke artwork   engraving posted one stroke at a time (M103 ... M104 per
                     stroke) lifts the head between every stroke. Consecutive
                     strokes are joined into one fly cut: the beam is gated once
                     and the G0/G1 distinction does the rest.
  * through-cuts     never touched. If one was inheriting its condition from
                     inside a rewritten block, its own condition is re-emitted.

Every output is proven before it is written: the output text is parsed again
from scratch and replayed, and every beam-on cutting move must match the
original exactly (same geometry, same order, correct condition).

Kept free of any GUI code so it can be tested headlessly.
"""

import math
import os
import re
from dataclasses import dataclass, field

VERSION = "1.0"
DEFAULT_TARGET = "E10"
STAMP_TAG = "(CLEAN THE CAM"
BOTTOM_LEFT = (10.0, 10.0)

# geometry tolerances (mm)
SAME_POINT = 0.0005      # coordinates are posted to 0.01, so this is "identical"
DUP_ROUND = 3            # decimals used to match retraced segments
TINY_MOVE = 0.05         # informational only
DEGENERATE_RADIUS = 0.005

RE_E = re.compile(r'^E(\d+)$')
RE_M103 = re.compile(r'^M103(?:A(\d*\.?\d*))?$')
RE_M104 = re.compile(r'^M104(?:\s*Z(-?\d*\.?\d*))?$')
RE_WORDS = re.compile(r'^(?:\s*[A-Z]\s*-?\d*\.?\d*)+\s*$')
RE_WORD = re.compile(r'([A-Z])\s*(-?\d*\.?\d*)')
RE_SHEET = re.compile(r'^\(\*SHEET\s+(-?[\d.]+)\s+(-?[\d.]+)')
RE_JOBTIME = re.compile(r'^\(JOB TIME\b(.*)\)\s*$')

MOTION_LETTERS = set('GXYIJR')


# ----------------------------------------------------------------------------
# options and result
# ----------------------------------------------------------------------------

@dataclass
class Options:
    target: str = DEFAULT_TARGET
    force_a0: bool = True
    home: str = 'keep'              # keep | bottom_left | custom
    home_xy: tuple = (None, None)
    end: str = 'start'              # home (G50) | start (G92 point) | custom
    end_xy: tuple = (None, None)
    stamp: bool = True
    cleanup: object = None          # None = ask, True = clean, False = leave


@dataclass
class Result:
    status: str = 'FAIL'            # PASS | WARN | FAIL | DECIDE
    text: str = ''                  # output file content (only when ok)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    cleanup: list = field(default_factory=list)   # candidates, see _find_cleanup
    preview: dict = field(default_factory=dict)
    changes: list = field(default_factory=list)   # human readable list of edits

    @property
    def ok(self):
        return self.status in ('PASS', 'WARN')

    @property
    def needs_decision(self):
        return self.status == 'DECIDE'


class Reject(Exception):
    """Input cannot be processed safely."""


# ----------------------------------------------------------------------------
# number formatting / parsing
# ----------------------------------------------------------------------------

def fmt(v):
    """cncKad style: 10 -> '10.', 10.5 -> '10.5', 0.25 -> '0.25'."""
    s = f"{float(v):.4f}".rstrip('0')
    if s in ('-0.', '-.'):
        s = '0.'
    return s


def _num(s, what):
    try:
        return float(s)
    except ValueError:
        raise Reject(f"Cannot read the number in {what!r}.")


# ----------------------------------------------------------------------------
# line model
# ----------------------------------------------------------------------------

class Line:
    """One program line. `src` is the 1-based line number in the source file,
    or None for a line Clean The CAM inserted."""

    __slots__ = ('text', 'src', 'kind', 'cond', 'pierce', 'z', 'g', 'x', 'y',
                 'i', 'j', 'r', 'letters')

    def __init__(self, text, src):
        self.text = text
        self.src = src
        self.parse()

    def parse(self):
        self.cond = self.pierce = self.z = self.g = None
        self.x = self.y = self.i = self.j = self.r = None
        self.letters = ''
        raw = self.text.strip()
        if not raw:
            self.kind = 'blank'
            return
        if raw.startswith('('):
            self.kind = 'comment'
            return
        if raw == '%':
            self.kind = 'pct'
            return
        code = raw.split('(')[0].strip()
        if m := RE_E.match(code):
            self.kind = 'E'
            self.cond = f"E{int(m.group(1))}"
            return
        if m := RE_M103.match(code):
            self.kind = 'M103'
            self.pierce = m.group(1)
            return
        if m := RE_M104.match(code):
            self.kind = 'M104'
            self.z = m.group(1)
            return
        if code and RE_WORDS.match(code):
            words = RE_WORD.findall(code)
            letters = ''.join(w[0] for w in words)
            self.letters = letters
            if set(letters) <= MOTION_LETTERS:
                gs = [w[1] for w in words if w[0] == 'G']
                if all(g.lstrip('0') in ('', '1', '2', '3') and g != '' for g in gs):
                    self.kind = 'motion'
                    if gs:
                        self.g = int(gs[-1])
                    for k, v in words:
                        if k in 'XYIJR':
                            setattr(self, k.lower(), _num(v, self.text))
                    return
        self.kind = 'other'

    def set(self, text):
        self.text = text
        self.parse()


def read_text(path):
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        text = raw.decode('ascii')
    except UnicodeDecodeError:
        text = raw.decode('latin-1')
    return text


def split_lines(text):
    eol = '\r\n' if '\r\n' in text else '\n'
    final_newline = text.endswith(('\n', '\r'))
    return text.splitlines(), eol, final_newline


# ----------------------------------------------------------------------------
# replay
# ----------------------------------------------------------------------------

def _arc_points(start, end, mode, i, j, r, steps_per_mm=4):
    """Points along a G2/G3 move (start excluded). Falls back to a chord."""
    sx, sy = start
    ex, ey = end
    if i is not None or j is not None:
        cx, cy = sx + (i or 0.0), sy + (j or 0.0)
    elif r is not None and r != 0:
        dx, dy = ex - sx, ey - sy
        d = math.hypot(dx, dy)
        if d == 0 or abs(r) < d / 2:
            return [end], d
        h = math.sqrt(max(r * r - d * d / 4, 0.0))
        mx, my = (sx + ex) / 2, (sy + ey) / 2
        ux, uy = -dy / d, dx / d
        # G2 = clockwise. R>0 = minor arc. Pick the centre that gives that.
        sign = 1 if (mode == 3) == (r > 0) else -1
        cx, cy = mx + sign * h * ux, my + sign * h * uy
    else:
        return [end], math.hypot(ex - sx, ey - sy)
    rad = math.hypot(sx - cx, sy - cy)
    a0 = math.atan2(sy - cy, sx - cx)
    a1 = math.atan2(ey - cy, ex - cx)
    if mode == 3:          # counter-clockwise
        sweep = (a1 - a0) % (2 * math.pi)
    else:
        sweep = -((a0 - a1) % (2 * math.pi))
    if abs(sweep) < 1e-12 and (i is not None or j is not None):
        sweep = 2 * math.pi if mode == 3 else -2 * math.pi   # full circle
    length = abs(sweep) * rad
    n = max(2, int(length * steps_per_mm))
    pts = [(cx + rad * math.cos(a0 + sweep * k / n), cy + rad * math.sin(a0 + sweep * k / n))
           for k in range(1, n)]
    pts.append(end)
    return pts, length


def replay(lines):
    """Walk the program. Returns (moves, spans, problems).

    move: dict(k, src, start, end, mode, i, j, r, beam, cond, span, length)
    span: one M103 ... M104 beam-on block.
    """
    pos = None
    mode = None
    beam = False
    cond = None
    cond_k = None
    moves, spans, problems = [], [], []
    cur = None
    for k, ln in enumerate(lines):
        kind = ln.kind
        if kind == 'E':
            cond, cond_k = ln.cond, k
            if beam:
                cur['conds'].add(cond)
                cur['e_lines'].append(k)
        elif kind == 'M103':
            if beam:
                problems.append((k, "beam switched on twice without an M104 between"))
            beam = True
            cur = dict(m103=k, m104=None, cond=cond, cond_k=cond_k, conds={cond},
                       e_lines=[], first=len(moves), last=None, rapid_on=0,
                       rapid_on_len=0.0, feed=0, feed_len=0.0)
            spans.append(cur)
        elif kind == 'M104':
            if not beam:
                problems.append((k, "M104 with the beam already off"))
            else:
                cur['m104'] = k
                cur['last'] = len(moves)
            beam = False
            cur = None
        elif kind == 'motion':
            if ln.g is not None:
                mode = ln.g
            if ln.x is None and ln.y is None and ln.i is None and ln.j is None:
                continue
            if mode is None:
                problems.append((k, "move with no G0/G1/G2/G3 in effect"))
                continue
            if pos is None:
                pos = (ln.x if ln.x is not None else 0.0, ln.y if ln.y is not None else 0.0)
                if beam:
                    problems.append((k, "cutting move before any position is known"))
                continue
            end = (ln.x if ln.x is not None else pos[0], ln.y if ln.y is not None else pos[1])
            if mode in (2, 3):
                _, length = _arc_points(pos, end, mode, ln.i, ln.j, ln.r)
            else:
                length = math.hypot(end[0] - pos[0], end[1] - pos[1])
            mv = dict(k=k, src=ln.src, start=pos, end=end, mode=mode, i=ln.i, j=ln.j,
                      r=ln.r, beam=beam, cond=cond, span=len(spans) - 1 if beam else None,
                      length=length)
            moves.append(mv)
            if beam:
                if mode == 0:
                    cur['rapid_on'] += 1
                    cur['rapid_on_len'] += length
                else:
                    cur['feed'] += 1
                    cur['feed_len'] += length
            pos = end
    if beam:
        problems.append((len(lines) - 1, "file ends with the beam still on"))
    return moves, spans, problems


def _rapid_key(m):
    return (round(m['start'][0], 4), round(m['start'][1], 4),
            round(m['end'][0], 4), round(m['end'][1], 4))


def _feed_key(m):
    """What must not change about a cutting move."""
    rnd = lambda v: None if v is None else round(v, 4)
    return (round(m['start'][0], 4), round(m['start'][1], 4),
            round(m['end'][0], 4), round(m['end'][1], 4),
            1 if m['mode'] == 1 else m['mode'], rnd(m['i']), rnd(m['j']), rnd(m['r']))


# ----------------------------------------------------------------------------
# the transform
# ----------------------------------------------------------------------------

def _classify(spans, target):
    for s in spans:
        etch_only = s['conds'] <= {target}
        if s['rapid_on'] > 0:
            s['type'] = 'fly' if etch_only else 'hatch'
        else:
            s['type'] = 'stroke' if etch_only else 'cut'


def _header_values(lines, body_start):
    info = dict(g92=None, g92_k=None, g92_count=0, g98=None, sheet=None, mat=None,
                part=None, stamp=False, oline=None, any_g91=False)
    for k, ln in enumerate(lines):
        t = ln.text.strip()
        if t.upper().startswith(STAMP_TAG):
            info['stamp'] = True
        code = t.split('(')[0].strip()
        if 'G91' in code.replace(' ', ''):
            info['any_g91'] = True
        if k >= body_start:
            continue
        if m := RE_SHEET.match(t):
            info['sheet'] = (float(m.group(1)), float(m.group(2)))
        if t.startswith('(MAT'):
            info['mat'] = t.strip('()').strip()
        if t.startswith('(PART SIZE'):
            info['part'] = t.strip('()').strip()
        if code.startswith('O') and info['oline'] is None:
            info['oline'] = k
        if code.startswith('G92'):
            info['g92_count'] += 1
            w = dict(RE_WORD.findall(code))
            if 'X' in w and 'Y' in w and info['g92'] is None:
                info['g92'] = (_num(w['X'], t), _num(w['Y'], t))
                info['g92_k'] = k
        if code.startswith('G98'):
            w = dict(RE_WORD.findall(code))
            if 'X' in w and 'Y' in w:
                info['g98'] = (_num(w['X'], t), _num(w['Y'], t))
    return info


def _joinable_gap(lines, a, b):
    """Lines strictly between span a's M104 and span b's M103 are only
    beam-off positioning (G0) moves - or nothing at all (off/on in place)."""
    mode = None
    for k in range(a + 1, b):
        ln = lines[k]
        if ln.kind == 'blank':
            continue
        if ln.kind != 'motion':
            return False
        if ln.g is not None:
            mode = ln.g
        if mode != 0:
            return False
    return True


def _find_cleanup(lines, moves, spans, target):
    """Candidates inside engrave blocks only. Through-cuts are reported, never edited."""
    fly_spans = {n for n, s in enumerate(spans) if s['rapid_on'] > 0}
    out = []
    seen = {}
    for idx, m in enumerate(moves):
        if not m['beam'] or m['mode'] == 0:
            continue
        span = spans[m['span']]
        in_etch = span['conds'] <= {target}
        zero = (abs(m['end'][0] - m['start'][0]) < SAME_POINT and
                abs(m['end'][1] - m['start'][1]) < SAME_POINT)
        if zero:
            if m['mode'] in (2, 3) and (m['i'] is not None or m['j'] is not None):
                rad = math.hypot(m['i'] or 0.0, m['j'] or 0.0)
                if rad >= DEGENERATE_RADIUS:
                    continue      # a genuine full circle
            what = 'zero-length arc' if m['mode'] in (2, 3) else 'zero-length move'
            out.append(dict(kind='zero', k=m['k'], src=m['src'], what=what,
                            action='delete' if in_etch else 'keep (through-cut)'))
            continue
        if m['mode'] != 1 or not in_etch:
            continue
        a = (round(m['start'][0], DUP_ROUND), round(m['start'][1], DUP_ROUND))
        b = (round(m['end'][0], DUP_ROUND), round(m['end'][1], DUP_ROUND))
        key = (min(a, b), max(a, b))
        if key in seen:
            nxt = moves[idx + 1] if idx + 1 < len(moves) else None
            # if the next move is a rapid (or the stroke ends) the pass can simply go
            last_in_span = (nxt is None or nxt['span'] != m['span'] or not nxt['beam']
                            or nxt['mode'] == 0)
            if last_in_span:
                action = 'delete'
            elif m['span'] in fly_spans:
                action = 'fly over'
            else:
                action = 'keep (would need a beam-on jump inside a single stroke)'
            out.append(dict(kind='dup', k=m['k'], src=m['src'], what='line engraved twice',
                            first=seen[key], length=m['length'], action=action))
        else:
            seen[key] = m['src']
    return out


def _next_motion(lines, k):
    for n in range(k + 1, len(lines)):
        if lines[n] is not None and lines[n].kind == 'motion':
            return n
    return None


def _apply_cleanup(lines, cands):
    """Edit lines in place (marks deletions with None). Returns removed src lines."""
    # effective mode of every motion line, so a deletion never changes the modal G
    mode = None
    eff = {}
    for k, ln in enumerate(lines):
        if ln is not None and ln.kind == 'motion':
            if ln.g is not None:
                mode = ln.g
            eff[k] = mode
    removed = set()
    for c in sorted(cands, key=lambda c: c['k'], reverse=True):
        if c['action'] not in ('delete', 'fly over'):
            continue
        k = c['k']
        ln = lines[k]
        nxt = _next_motion(lines, k)
        if nxt is not None and lines[nxt] is not None and lines[nxt].g is None:
            # the next move relied on this line's (or an earlier) modal G
            lines[nxt].set(f"G{eff[nxt]}" + lines[nxt].text.lstrip())
        if c['action'] == 'delete':
            lines[k] = None
        else:
            parts = []
            if ln.x is not None:
                parts.append(f"X{fmt(ln.x)}")
            if ln.y is not None:
                parts.append(f"Y{fmt(ln.y)}")
            ln.set("G0" + ''.join(parts))
        removed.add(c['src'])
    return removed


def process(source, opts=None, name=None):
    """source: path, or the program text itself. Returns a Result."""
    opts = opts or Options()
    r = Result()
    try:
        _process(source, opts, r, name)
    except Reject as ex:
        r.errors.append(str(ex))
        r.status = 'FAIL'
        r.text = ''
    return r


def _process(source, opts, r, name):
    if '\n' in source or '\r' in source:
        text = source
    else:
        text = read_text(source)
    raw_lines, eol, final_nl = split_lines(text)
    st = r.stats
    st['lines_in'] = len(raw_lines)

    target = opts.target.strip().upper()
    if not RE_E.match(target):
        raise Reject(f"Engrave condition '{opts.target}' is not of the form E<number>.")
    target = f"E{int(target[1:])}"
    st['target'] = target

    lines = [Line(t, n + 1) for n, t in enumerate(raw_lines)]
    orig_moves, orig_spans, problems = replay(lines)
    if problems:
        k, msg = problems[0]
        raise Reject(f"Line {k + 1}: {msg}. The beam on/off structure is broken - "
                     f"is the file complete?")
    if not orig_spans:
        raise Reject("No M103 in this file - it contains no beam-on command at all.")

    body_start = min(orig_spans[0]['m103'],
                     orig_spans[0]['cond_k'] if orig_spans[0]['cond_k'] is not None else 10 ** 9)
    body_end = orig_spans[-1]['m104']
    info = _header_values(lines, body_start)
    st['header'] = info
    if info['stamp']:
        raise Reject("This file has already been through Clean The CAM (it carries the "
                     "stamp). Run the original cncKad post instead.")
    if info['any_g91']:
        raise Reject("The file uses G91 (incremental). Only absolute (G90) programs are supported.")

    for k in range(body_start, body_end + 1):
        if lines[k].kind == 'other':
            t = lines[k].text.strip()
            hint = " (Z motion)" if 'Z' in t else ""
            raise Reject(f"Line {k + 1}: unrecognised code in the cutting section{hint}: "
                         f"'{t}'. Nothing was written.")

    _classify(orig_spans, target)
    st['spans_in'] = len(orig_spans)
    st['types_in'] = {t: sum(1 for s in orig_spans if s['type'] == t)
                      for t in ('hatch', 'fly', 'stroke', 'cut')}

    # ---------------- plan: joins -------------------------------------------
    runs, run = [], []
    for n, s in enumerate(orig_spans):
        etch = s['type'] in ('stroke', 'fly')
        if etch and run:
            prev = orig_spans[run[-1]]
            if lines[prev['m104']].z is None and _joinable_gap(lines, prev['m104'], s['m103']):
                run.append(n)
                continue
        if len(run) > 1:
            runs.append(run)
        run = [n] if etch else []
    if len(run) > 1:
        runs.append(run)

    out = list(lines)                 # same objects; None marks deletion
    drop = set()
    joined_strokes = 0
    for run in runs:
        for a, b in zip(run, run[1:]):
            drop.add(orig_spans[a]['m104'])
            drop.add(orig_spans[b]['m103'])
        joined_strokes += len(run)
        r.changes.append(f"joined {len(run)} strokes into one fly cut "
                         f"(source lines {orig_spans[run[0]]['m103'] + 1}-"
                         f"{orig_spans[run[-1]]['m104'] + 1})")
    st['runs'] = [(orig_spans[run[0]]['m103'] + 1, orig_spans[run[-1]]['m104'] + 1, len(run))
                  for run in runs]
    st['joined_strokes'] = joined_strokes
    st['gates_removed'] = len(drop) // 2

    # ---------------- plan: hatch retarget ----------------------------------
    rewrites = {}       # k -> new text
    inserts_before = {}  # k -> [texts]
    retargeted = {}
    pierces = 0
    prev_end = -1
    for n, s in enumerate(orig_spans):
        if s['type'] == 'hatch':
            for k in s['e_lines']:
                if lines[k].cond != target:
                    retargeted[lines[k].cond] = retargeted.get(lines[k].cond, 0) + 1
                    rewrites[k] = target
            ck = s['cond_k']
            if s['cond'] != target:
                if ck is not None and ck > prev_end:
                    retargeted[s['cond']] = retargeted.get(s['cond'], 0) + 1
                    rewrites[ck] = target
                else:
                    inserts_before.setdefault(s['m103'], []).append(target)
            r.changes.append(f"hatch at source lines {s['m103'] + 1}-{s['m104'] + 1}: "
                             f"{', '.join(sorted(c for c in s['conds'] if c))} -> {target}")
        if opts.force_a0 and s['type'] in ('hatch', 'fly', 'stroke') and s['m103'] not in drop:
            p = lines[s['m103']].pierce
            if p is None or p == '' or float(p) != 0.0:
                rewrites[s['m103']] = 'M103A0'
                pierces += 1
        prev_end = s['m104']
    st['retargeted'] = retargeted
    st['pierces_a0'] = pierces
    st['hatch_blocks'] = sum(1 for s in orig_spans if s['type'] == 'hatch')

    for k, new in rewrites.items():
        old = out[k].text
        # keep whatever trails the code (comments) intact
        out[k] = Line(old.replace(old.strip().split('(')[0].strip(), new, 1), out[k].src)
    built = []
    for k, ln in enumerate(out):
        for t in inserts_before.get(k, []):
            built.append(Line(t, None))
        if k in drop:
            continue
        built.append(ln)
    out = built

    # ---------------- inheritance fix ----------------------------------------
    orig_cut_cond = {s['m103'] + 1: s['cond'] for s in orig_spans if s['type'] == 'cut'}
    reemitted = []
    for _ in range(len(orig_cut_cond) + 1):
        _, spans_now, _ = replay(out)
        fixed = False
        last_m104 = None
        for s in spans_now:
            src = out[s['m103']].src
            want = orig_cut_cond.get(src)
            if want is not None and s['cond'] != want:
                at = (last_m104 + 1) if last_m104 is not None else s['m103']
                out.insert(at, Line(want, None))
                reemitted.append((src, want))
                fixed = True
                break
            last_m104 = s['m104']
        if not fixed:
            break
    st['reemitted'] = reemitted
    for src, c in reemitted:
        r.notes.append(f"{c} re-emitted before the through-cut at source line {src}: it had "
                       f"no condition of its own and was inheriting one from inside a "
                       f"rewritten block.")

    # ---------------- cleanup candidates -------------------------------------
    moves_now, spans_now, _ = replay(out)
    cands = _find_cleanup(out, moves_now, spans_now, target)
    r.cleanup = cands
    actionable = [c for c in cands if c['action'] in ('delete', 'fly over')]
    st['cleanup_found'] = len(cands)
    st['cleanup_actionable'] = len(actionable)
    removed = set()
    if actionable:
        if opts.cleanup is None:
            r.status = 'DECIDE'
            return
        if opts.cleanup:
            work = list(out)
            removed = _apply_cleanup(work, actionable)
            out = [ln for ln in work if ln is not None]
            r.changes.append(f"cleanup: removed {len(removed)} junk / retraced move(s)")
        else:
            r.notes.append(f"Cleanup declined: {len(actionable)} junk / retraced move(s) "
                           f"left as posted.")
    kept = [c for c in cands if c not in actionable]
    if kept:
        r.warnings.append(
            f"{len(kept)} junk / retraced move(s) cannot be cleaned automatically and were "
            f"left in place: " + ', '.join(f"line {c['src']} {c['what']} - {c['action']}"
                                           for c in kept[:6]))
    st['cleanup_removed'] = sorted(removed)

    # ---------------- home (G92) ---------------------------------------------
    home = info['g92']
    if opts.home != 'keep':
        if info['g92_count'] != 1 or home is None:
            raise Reject(f"Expected exactly one 'G92 X.. Y..' line in the header, found "
                         f"{info['g92_count']}. The home cannot be changed safely.")
        if opts.home == 'bottom_left':
            new_home = BOTTOM_LEFT
        elif opts.home == 'custom':
            new_home = _xy(opts.home_xy, 'custom home')
        else:
            raise Reject(f"Unknown home option '{opts.home}'.")
        k = _find_src(out, info['g92_k'] + 1)
        out[k] = Line(f"G92 X{fmt(new_home[0])} Y{fmt(new_home[1])}", out[k].src)
        if new_home != home:
            r.changes.append(f"home G92: X{fmt(home[0])} Y{fmt(home[1])} -> "
                             f"X{fmt(new_home[0])} Y{fmt(new_home[1])}")
        home = new_home
    st['home'] = home

    # ---------------- ending ---------------------------------------------------
    last_m104 = max(k for k, ln in enumerate(out) if ln.kind == 'M104')
    tail = out[last_m104 + 1:]
    old_codes = []
    kept_tail = []
    for ln in tail:
        if ln.kind in ('comment', 'blank', 'pct'):
            kept_tail.append(ln)
            continue
        code = ln.text.strip().split('(')[0].strip()
        w = RE_WORD.findall(code)
        letters = {a for a, _ in w}
        gs = {int(v) for a, v in w if a == 'G' and v}
        ms = {int(v) for a, v in w if a == 'M' and v}
        if (code and RE_WORDS.match(code) and letters <= set('GMXY')
                and gs <= {0, 90, 50} and ms <= {30}):
            old_codes.append(ln.text.strip())
            continue
        raise Reject(f"Unrecognised line in the program ending: '{ln.text.strip()}'. "
                     f"The ending cannot be replaced safely.")
    if opts.end == 'home':
        new_end = ['G50']
    elif opts.end == 'start':
        if home is None:
            raise Reject("'Return to start' needs a G92 home in the header and none was found.")
        new_end = [f"G90 G00 X{fmt(home[0])} Y{fmt(home[1])}", 'M30']
    elif opts.end == 'custom':
        ex, ey = _xy(opts.end_xy, 'custom end position')
        new_end = [f"G90 G00 X{fmt(ex)} Y{fmt(ey)}", 'M30']
    else:
        raise Reject(f"Unknown end option '{opts.end}'.")
    st['end_old'] = old_codes
    st['end_new'] = new_end
    if old_codes != new_end:
        r.changes.append(f"ending: {' / '.join(old_codes) or '(none)'} -> {' / '.join(new_end)}")

    # job time comment is cncKad's estimate for the ORIGINAL program
    new_tail = []
    for ln in kept_tail:
        if (m := RE_JOBTIME.match(ln.text.strip())) and opts.stamp:
            t = m.group(1).strip()
            ln = Line(f"(JOB TIME {t} - CNCKAD ESTIMATE BEFORE CLEANUP)", ln.src)
        new_tail.append(ln)
    pct_at = next((n for n, ln in enumerate(new_tail) if ln.kind == 'pct'), len(new_tail))
    new_tail[pct_at:pct_at] = [Line(t, None) for t in new_end]
    out = out[:last_m104 + 1] + new_tail

    # ---------------- stamp ----------------------------------------------------
    if opts.stamp:
        bits = [f"CLEAN THE CAM {VERSION}", target]
        if opts.force_a0:
            bits.append("A0")
        if joined_strokes:
            bits.append(f"{joined_strokes} STROKES JOINED")
        if st['hatch_blocks']:
            bits.append(f"{st['hatch_blocks']} HATCH RETARGETED")
        if home is not None:
            bits.append(f"HOME X{fmt(home[0])} Y{fmt(home[1])}")
        stamp = Line("(" + ' - '.join(bits) + ")", None)
        at = (_find_src(out, info['oline'] + 1) + 1) if info['oline'] is not None else 1
        out.insert(at, stamp)

    if not runs and not st['hatch_blocks']:
        r.warnings.append("No fly-cut hatch and no joinable strokes were found - the "
                          "cutting section is unchanged. Only the header/ending options "
                          "were applied.")

    # ---------------- verify ---------------------------------------------------
    text_out = eol.join(ln.text for ln in out) + (eol if final_nl else '')
    _verify(text_out, orig_moves, orig_spans, removed, target, info, opts.force_a0, r)
    st['lines_out'] = len(out)
    if r.errors:
        r.status = 'FAIL'
        r.text = ''
        return
    r.text = text_out
    r.status = 'WARN' if r.warnings else 'PASS'


def _xy(xy, what):
    try:
        x, y = float(xy[0]), float(xy[1])
    except (TypeError, ValueError, IndexError):
        raise Reject(f"The {what} needs a number for both X and Y.")
    return (x, y)


def _find_src(out, src):
    for n, ln in enumerate(out):
        if ln.src == src:
            return n
    raise Reject(f"Internal error: source line {src} went missing.")


# ----------------------------------------------------------------------------
# independent verification of the written text
# ----------------------------------------------------------------------------

def _verify(text_out, orig_moves, orig_spans, removed, target, info, force_a0, r):
    st = r.stats
    lines, _, _ = split_lines(text_out)
    new = [Line(t, n + 1) for n, t in enumerate(lines)]
    moves, spans, problems = replay(new)
    for k, msg in problems[:3]:
        r.errors.append(f"Output line {k + 1}: {msg}.")
    _classify(spans, target)

    # 1. every beam-on cutting move, same geometry, same order
    want = [m for m in orig_moves if m['beam'] and m['mode'] != 0 and m['src'] not in removed]
    got = [m for m in moves if m['beam'] and m['mode'] != 0]
    if [_feed_key(m) for m in want] != [_feed_key(m) for m in got]:
        n = next((n for n, (a, b) in enumerate(zip(want, got)) if _feed_key(a) != _feed_key(b)),
                 min(len(want), len(got)))
        where = f"source line {want[n]['src']}" if n < len(want) else "the end"
        r.errors.append(f"Cutting path verification failed at move {n + 1} ({where}): the "
                        f"output does not reproduce the original beam-on moves "
                        f"({len(want)} expected, {len(got)} found). Nothing was written.")
        return
    st['feed_moves'] = len(got)

    # 2. conditions: engraving at the target, every through-cut keeps its own
    orig_type = {}
    for s in orig_spans:
        for m in orig_moves[s['first']:s['last']]:
            orig_type[m['src']] = s['type']
    bad = []
    for a, b in zip(want, got):
        if orig_type.get(a['src']) == 'cut':
            if b['cond'] != a['cond']:
                bad.append(f"line {a['src']} through-cut {a['cond']} -> {b['cond']}")
        elif b['cond'] != target:
            bad.append(f"line {a['src']} engraving runs at {b['cond']}, not {target}")
    if bad:
        r.errors.append("Condition check failed: " + '; '.join(bad[:6]))
    leftover = sorted({c for s in spans if s['type'] in ('fly', 'stroke', 'hatch') and
                       s['rapid_on'] for c in s['conds'] if c != target} - {None})
    if leftover:
        r.errors.append(f"Conditions other than {target} survive inside a fly block: "
                        f"{', '.join(leftover)}.")
    cut_spans = [s for s in spans if s['type'] == 'cut']
    for s in cut_spans:
        if s['cond'] in (None, target):
            r.errors.append(f"Through-cut at output line {s['m103'] + 1} has no cutting "
                            f"condition of its own ({s['cond'] or 'none'}).")

    # 3. pierce
    live = [s['m103'] + 1 for s in spans if s['type'] != 'cut'
            and (new[s['m103']].pierce in (None, '') or float(new[s['m103']].pierce) != 0)]
    if live:
        msg = f"Pierce dwell still active on engraving at output line(s) {live[:5]}."
        (r.errors if force_a0 else r.warnings).append(msg)

    # 4. head-down travel over cut metal: no fly block after the first through-cut
    first_cut = next((n for n, s in enumerate(spans) if s['type'] == 'cut'), None)
    if first_cut is not None:
        late = [s for s in spans[first_cut + 1:] if s['rapid_on'] > 0]
        if late:
            r.errors.append(
                f"A fly block (output line {late[0]['m103'] + 1}) runs AFTER a through-cut "
                f"(output line {spans[first_cut]['m103'] + 1}). In fly cut the head stays "
                f"down across the rapids and could catch a cut edge or tipped slug. Engraving "
                f"must come before cutting - re-sequence in cncKad.")

    # 5. Z inside a fly block
    for s in spans:
        if s['rapid_on']:
            for k in range(s['m103'] + 1, s['m104']):
                if 'Z' in new[k].text.split('(')[0]:
                    r.errors.append(f"Z motion inside a fly block at output line {k + 1}. "
                                    f"The head must stay down for the whole block.")
                    break

    # 6. beam-on rapids: totals, what is new, longest jump, sheet edge
    # matched by geometry - line numbers shift once gates are removed
    orig_on = {_rapid_key(m) for m in orig_moves if m['beam'] and m['mode'] == 0}
    on = [m for m in moves if m['beam'] and m['mode'] == 0]
    added = [m for m in on if _rapid_key(m) not in orig_on]
    st['rapid_on_total'] = sum(m['length'] for m in on)
    st['rapid_on_moves'] = len(on)
    st['rapid_on_added'] = sum(m['length'] for m in added)
    st['rapid_on_added_moves'] = len(added)
    longest = max(added, key=lambda m: m['length'], default=None)
    st['longest_added'] = (longest['length'], longest['k'] + 1) if longest else None
    if added:
        r.warnings.append(
            f"The beam is now commanded ON across {st['rapid_on_added']:.0f} mm of rapid "
            f"travel ({len(added)} moves, longest {longest['length']:.1f} mm at output line "
            f"{longest['k'] + 1}) that cncKad had gated off stroke by stroke. Safe only if "
            f"the control inhibits the beam on G0 in fly cut. Prove it on scrap first.")
    sheet, g98 = info.get('sheet'), info.get('g98')
    if on:
        if sheet and g98:
            w, h = sheet
            ox, oy = g98
            off = [m for m in on for (px, py) in (m['start'], m['end'])
                   if not (-0.001 <= px + ox <= w + 0.001 and -0.001 <= py + oy <= h + 0.001)]
            if off:
                m = off[0]
                r.warnings.append(
                    f"{len(off)} head-down rapid(s) leave the {w:g} x {h:g} sheet (first at "
                    f"output line {m['k'] + 1}). The height sensor may lose the sheet edge.")
        else:
            r.warnings.append("No (*SHEET ..) / G98 in the header - could not check that "
                              "head-down rapids stay on the sheet.")

    # 7. junk left in through-cuts / informational tiny moves
    tiny = sum(1 for m in got if 0 < m['length'] < TINY_MOVE)
    st['tiny_moves'] = tiny

    # 8. preview geometry
    r.preview = _preview(moves, spans, target, info, orig_on)
    st['spans_out'] = len(spans)
    st['fly_blocks'] = [(s['m103'] + 1, s['m104'] + 1, s['feed'], s['feed_len'],
                         s['rapid_on'], s['rapid_on_len']) for s in spans if s['rapid_on']]
    st['cut_blocks'] = [(s['m103'] + 1, s['m104'] + 1, s['cond'], s['feed_len'])
                        for s in cut_spans]


def _preview(moves, spans, target, info, orig_on):
    segs = []
    for m in moves:
        if m['beam'] and m['mode'] != 0:
            kind = 'etch' if m['cond'] == target and spans[m['span']]['type'] != 'cut' else 'cut'
        elif m['beam']:
            kind = 'rapid_on_new' if _rapid_key(m) not in orig_on else 'rapid_on'
        else:
            kind = 'rapid_off'
        if m['mode'] in (2, 3):
            pts, _ = _arc_points(m['start'], m['end'], m['mode'], m['i'], m['j'], m['r'])
            pts = [m['start']] + pts
        else:
            pts = [m['start'], m['end']]
        segs.append((kind, pts))
    return dict(segs=segs, sheet=info.get('sheet'), offset=info.get('g98'))


# ----------------------------------------------------------------------------
# files and report
# ----------------------------------------------------------------------------

def output_paths(src):
    base, ext = os.path.splitext(src)
    return f"{base}_clean{ext or '.ENC'}", f"{base}_clean_report.txt"


def write_output(path, text):
    with open(path, 'w', newline='', encoding='ascii', errors='strict') as f:
        f.write(text)


def format_report(src, dst, r):
    st = r.stats
    L = []
    w = L.append
    bar = "-" * 64
    w("=" * 64)
    w(f"  CLEAN THE CAM {VERSION}")
    w("=" * 64)
    w("")
    w(f"source : {src}")
    w(f"output : {dst if r.ok else '(not written)'}")
    w("")
    banner = {'PASS': "PASS - output written",
              'WARN': "PASS WITH WARNINGS - output written, read the warnings",
              'FAIL': "FAIL - nothing written, do not run this file",
              'DECIDE': "WAITING - cleanup decision needed"}[r.status]
    w(f"  RESULT: {banner}")
    hdr = st.get('header') or {}
    if hdr:
        w("")
        w(bar)
        w("FILE")
        w(bar)
        if hdr.get('mat'):
            w(f"  material              {hdr['mat']}")
        if hdr.get('part'):
            w(f"  part                  {hdr['part']}")
        w(f"  lines                 {st.get('lines_in', '?')} in, {st.get('lines_out', '-')} out")
        t = st.get('types_in') or {}
        if t:
            w(f"  beam-on blocks        {st.get('spans_in')}  (hatch {t['hatch']}, "
              f"stroke {t['stroke']}, fly {t['fly']}, through-cut {t['cut']})")
    if r.changes:
        w("")
        w(bar)
        w("CHANGES")
        w(bar)
        for c in r.changes:
            w(f"  * {c}")
        if st.get('gates_removed'):
            w(f"  * head lift/lower cycles removed: {st['gates_removed']}")
        if st.get('pierces_a0'):
            w(f"  * pierce set to A0 on {st['pierces_a0']} engrave block(s)")
    if r.ok:
        w("")
        w(bar)
        w("VERIFIED")
        w(bar)
        w(f"  cutting moves         {st.get('feed_moves')} beam-on moves replayed from the "
          f"output - identical to the original")
        if st.get('cleanup_removed'):
            w(f"                        (except {len(st['cleanup_removed'])} removed by cleanup)")
        w(f"  beam-on rapids        {st.get('rapid_on_moves', 0)} moves, "
          f"{st.get('rapid_on_total', 0):.1f} mm total")
        if st.get('rapid_on_added_moves'):
            lo = st['longest_added']
            w(f"    added by joining    {st['rapid_on_added_moves']} moves, "
              f"{st['rapid_on_added']:.1f} mm, longest {lo[0]:.1f} mm (line {lo[1]})")
        for a, b, nf, lf, nr, lr in st.get('fly_blocks', []):
            ratio = f"{lr / lf:.1f}:1" if lf else '-'
            w(f"  fly block             lines {a}-{b}: {nf} cuts {lf:.1f} mm, "
              f"{nr} rapids {lr:.1f} mm (rapid:cut {ratio})")
        for a, b, c, lf in st.get('cut_blocks', []):
            w(f"  through-cut           lines {a}-{b}: {c}, {lf:.1f} mm - untouched")
        if st.get('tiny_moves'):
            w(f"  tiny moves (<{TINY_MOVE} mm)  {st['tiny_moves']} (information only)")
    if r.cleanup:
        w("")
        w(bar)
        w("JUNK / RETRACED MOVES FOUND")
        w(bar)
        for c in r.cleanup[:40]:
            extra = f" (first cut at line {c['first']})" if c.get('first') else ''
            w(f"  source line {c['src']:<6} {c['what']}{extra} -> {c['action']}")
        if len(r.cleanup) > 40:
            w(f"  ... and {len(r.cleanup) - 40} more")
    for bucket, label in (('errors', 'ERROR'), ('warnings', 'WARNING'), ('notes', 'NOTE')):
        items = getattr(r, bucket)
        if items:
            w("")
            w(bar)
            for m in items:
                w(f"  [{label}] {m}")
    w("")
    w(bar)
    w("VERIFY BEFORE CYCLE START")
    w(bar)
    w("  1. In a fly block the beam is commanded ON across every G0 and the head")
    w("     stays down. Safe only if the control inhibits the beam on rapids in")
    w("     fly-cut mode. Prove it on scrap - if wrong, every fly-over marks the part.")
    w("  2. Check the engrave condition's feed suits the fly-cut turnaround.")
    w("  3. Dry-run or run on scrap first.")
    w("")
    return "\n".join(L)


def describe_cleanup(r, limit=12):
    """Short text for the cleanup question."""
    acts = [c for c in r.cleanup if c['action'] in ('delete', 'fly over')]
    zero = [c for c in acts if c['kind'] == 'zero']
    dup = [c for c in acts if c['kind'] == 'dup']
    parts = []
    if zero:
        parts.append(f"{len(zero)} zero-length move(s)/arc(s) - some controls alarm on these. "
                     f"Cleanup deletes them (no change to the shape).")
    if dup:
        parts.append(f"{len(dup)} line(s) engraved twice ({sum(c['length'] for c in dup):.1f} mm) "
                     f"- those spots burn darker. Cleanup skips the second pass.")
    lines = ', '.join(str(c['src']) for c in acts[:limit])
    more = f" and {len(acts) - limit} more" if len(acts) > limit else ''
    return "\n\n".join(parts) + f"\n\nSource lines: {lines}{more}."
