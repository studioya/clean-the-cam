"""Remembered choices, kept in the user's profile (not next to the exe)."""

import json
import os

DEFAULTS = {
    'target': 'E10',
    'force_a0': True,
    'save_report': True,
    'stamp': True,
    'home': 'bottom_left',          # keep | bottom_left | custom
    'home_x': '',
    'home_y': '',
    'end': 'start',                 # home | start | custom
    'end_x': '',
    'end_y': '',
    'last_dir': '',
    'dnc_exe': r'C:\Metalix\DNC.19\DNC2000.exe',
    'dnc_progid': 'DNC.Document',   # what cncKad's simulator uses
    'dnc_method': 'LoadFile',
}


def path():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'CleanTheCAM', 'settings.json')


def load():
    s = dict(DEFAULTS)
    try:
        with open(path(), encoding='utf-8') as f:
            saved = json.load(f)
        s.update({k: v for k, v in saved.items() if k in DEFAULTS})
        # versions before the DNC automation was found saved these empty
        for k in ('dnc_exe', 'dnc_progid', 'dnc_method'):
            if not str(s.get(k) or '').strip():
                s[k] = DEFAULTS[k]
    except (OSError, ValueError):
        pass
    return s


def save(s):
    p = path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump({k: s.get(k, v) for k, v in DEFAULTS.items()}, f, indent=2)
    except OSError:
        pass
