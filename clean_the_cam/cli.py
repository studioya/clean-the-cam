"""Command line: clean-the-cam FILE_OR_FOLDER [...]"""

import argparse
import glob
import os
import sys

from . import core


def _xy_or(value, words):
    if value in words:
        return value, (None, None)
    try:
        x, y = value.split(',')
        float(x), float(y)
        return 'custom', (x, y)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected one of {', '.join(words)} or X,Y")


def expand(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            found = sorted(set(glob.glob(os.path.join(p, '*.ENC')) +
                               glob.glob(os.path.join(p, '*.enc'))))
            out += [f for f in found if not os.path.splitext(f)[0].endswith('_clean')]
        else:
            out.append(p)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog='clean-the-cam',
                                 description="Turn cncKad fly cuts and stroke engraving into "
                                             "fast fly-cut engraves.")
    ap.add_argument('paths', nargs='+', help=".ENC files or folders of them")
    ap.add_argument('--target', default=core.DEFAULT_TARGET, help="engrave condition (E10)")
    ap.add_argument('--keep-pierce', action='store_true', help="do not force pierce to A0")
    ap.add_argument('--home', default='keep',
                    type=lambda v: _xy_or(v, ('keep', 'bottom-left')),
                    help="keep | bottom-left | X,Y   (default keep)")
    ap.add_argument('--end', default='start',
                    type=lambda v: _xy_or(v, ('home', 'start')),
                    help="home (G50) | start (G92 point) | X,Y   (default start)")
    ap.add_argument('--cleanup', choices=('yes', 'no'), default='no',
                    help="remove zero-length / retraced moves when found (default no)")
    ap.add_argument('--no-stamp', action='store_true', help="do not stamp the header")
    ap.add_argument('--no-report', action='store_true', help="do not write report files")
    ap.add_argument('--dry-run', action='store_true', help="check only, write nothing")
    a = ap.parse_args(argv)

    if not isinstance(a.home, tuple):
        a.home = _xy_or(a.home, ('keep', 'bottom-left'))
    if not isinstance(a.end, tuple):
        a.end = _xy_or(a.end, ('home', 'start'))
    home, home_xy = a.home
    end, end_xy = a.end
    opts = core.Options(target=a.target, force_a0=not a.keep_pierce,
                        home=home.replace('-', '_'), home_xy=home_xy,
                        end=end, end_xy=end_xy, stamp=not a.no_stamp,
                        cleanup=(a.cleanup == 'yes'))
    files = expand(a.paths)
    if not files:
        print("no .ENC files found", file=sys.stderr)
        return 2
    worst = 0
    for src in files:
        dst, rep = core.output_paths(src)
        r = core.process(src, opts)
        if r.ok and not a.dry_run:
            core.write_output(dst, r.text)
        if not a.no_report and not a.dry_run:
            with open(rep, 'w', encoding='utf-8') as f:
                f.write(core.format_report(src, dst, r))
        extra = ''
        found = [c for c in r.cleanup if c['action'] in ('delete', 'fly over')]
        if found and a.cleanup == 'no':
            extra = f"  ({len(found)} junk/retraced moves left - use --cleanup yes)"
        first = (r.errors or r.warnings or [''])[0]
        print(f"{r.status:<5} {src}{extra}")
        if first:
            print(f"      {first[:160]}")
        worst = max(worst, {'PASS': 0, 'WARN': 1}.get(r.status, 2))
    return worst


if __name__ == '__main__':
    sys.exit(main())
