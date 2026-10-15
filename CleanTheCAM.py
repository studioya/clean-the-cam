#!/usr/bin/env python3
"""Entry point for running from source and for the PyInstaller build.

    python CleanTheCAM.py                      the window
    python CleanTheCAM.py a.ENC b.ENC          the window, files preselected
    python CleanTheCAM.py --cli FOLDER ...     batch, no window (see --cli --help)
"""

from clean_the_cam.__main__ import run

if __name__ == '__main__':
    run()
