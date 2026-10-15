"""
Test loading a file into DNC exactly as Clean The CAM's "Send to DNC" does.

    python tools\\dnc_test_load.py "D:\\path\\to\\file.ENC"

1. Opens DNC.Document and calls LoadFile with the path by reference.
2. Finds DNC's (hidden) window and shows it.
3. Waits for Enter, then lets go of DNC so you can see whether it stays open.

Use a known-good cncKad post.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

try:
    import win32com.client  # noqa: F401
except ImportError:
    sys.exit("pywin32 is missing:  python -m pip install pywin32")

from clean_the_cam import dnc, settings  # noqa: E402

if len(sys.argv) != 2 or not os.path.isfile(sys.argv[1]):
    sys.exit('usage: python tools\\dnc_test_load.py "D:\\path\\to\\file.ENC"')
path = os.path.abspath(sys.argv[1])
cfg = settings.DEFAULTS

print(f"1. LoadFile({path!r}) by reference ...")
try:
    obj = dnc._load(cfg['dnc_progid'], cfg['dnc_method'], path)
    print("   accepted")
except Exception as ex:
    sys.exit(f"   failed: {ex}")

print("2. Showing DNC's window ...")
wins = dnc._dnc_windows(cfg['dnc_exe'])
print(f"   DNC windows found: {len(wins)}")
print("   shown" if dnc.show_dnc(cfg['dnc_exe']) else "   could not show a window")

print("\nLook at DNC now:")
print("  a. Is the DNC window visible?")
print("  b. Is the file loaded and ready to send?")
print("  c. Did it start sending on its own?")
input("\nPress Enter to let go of DNC ...")
del obj
time.sleep(3)
print("\nd. Released. Is DNC still open? Report a, b, c and d.")
