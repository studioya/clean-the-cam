"""
One controlled test of DNC.Document.LoadFile - the call cncKad's simulator uses.

    python tools\\dnc_test_load.py "D:\\path\\to\\file.ENC"

It opens DNC the way cncKad does, calls LoadFile with the file, then waits for
you to press Enter before letting go of DNC, so you can see what DNC does.
Use a known-good cncKad post for the test.
"""

import os
import sys
import time

try:
    import pythoncom
    import win32com.client
except ImportError:
    sys.exit("pywin32 is missing:  python -m pip install pywin32")

if len(sys.argv) != 2 or not os.path.isfile(sys.argv[1]):
    sys.exit('usage: python tools\\dnc_test_load.py "D:\\path\\to\\file.ENC"')
path = os.path.abspath(sys.argv[1])

print(f"Opening DNC.Document ...")
dnc = win32com.client.Dispatch("DNC.Document")
print(f"Calling LoadFile({path!r}) ...")
t = time.time()
try:
    ret = dnc.LoadFile(path)
    print(f"LoadFile returned {ret!r} after {time.time() - t:.1f} s")
except pythoncom.com_error as ex:
    print(f"LoadFile failed: {ex}")

print("\nLook at DNC now:")
print("  1. Did a DNC window appear?")
print("  2. Is the file loaded and ready to send?")
print("  3. Did it start sending on its own?")
input("\nPress Enter to let go of DNC (then watch whether DNC stays open) ...")
del dnc
time.sleep(3)
print("Released. Is DNC still open? Then you're done - report what you saw.")
