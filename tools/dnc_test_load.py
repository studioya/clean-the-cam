"""
Find the form of DNC.Document.LoadFile that DNC accepts - the call cncKad's
simulator uses.

    python tools\\dnc_test_load.py "D:\\path\\to\\file.ENC"

Tries each way of passing the path, stops at the first one DNC accepts, and
waits for Enter before letting go of DNC so you can watch what it does. A form
DNC rejects does nothing. Use a known-good cncKad post.
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

M, GET, PUT = pythoncom.DISPATCH_METHOD, pythoncom.DISPATCH_PROPERTYGET, pythoncom.DISPATCH_PROPERTYPUT
BSTR, BYREF, VARIANT, I4 = (pythoncom.VT_BSTR, pythoncom.VT_BYREF, pythoncom.VT_VARIANT,
                            pythoncom.VT_I4)

print("Opening DNC.Document ...")
disp = win32com.client.Dispatch("DNC.Document")._oleobj_
known = {}
for name in ("LoadFile", "SendFile", "OpenFile", "Send", "FileName", "Visible", "Machine"):
    try:
        known[name] = disp.GetIDsOfNames(name)
    except pythoncom.com_error:
        pass
print("Names DNC knows:", ", ".join(f"{n} (id {i})" for n, i in known.items()) or "none")
dispid = known.get("LoadFile")
if dispid is None:
    sys.exit("DNC does not know LoadFile.")

VT_EMPTY = pythoncom.VT_EMPTY
FORMS = [
    ("method, path as text",
     lambda: disp.InvokeTypes(dispid, 0, M, (VARIANT, 0), ((BSTR, 1),), path)),
    ("setting: LoadFile = path",
     lambda: disp.InvokeTypes(dispid, 0, PUT, (VT_EMPTY, 0), ((BSTR, 1),), path)),
    ("method, path by reference",
     lambda: disp.InvokeTypes(dispid, 0, M, (VARIANT, 0), ((BSTR | BYREF, 3),), path)),
    ("method, path as variant by reference",
     lambda: disp.InvokeTypes(dispid, 0, M, (VARIANT, 0), ((VARIANT | BYREF, 3),), path)),
    ("method, path + 0",
     lambda: disp.InvokeTypes(dispid, 0, M, (VARIANT, 0), ((BSTR, 1), (I4, 1)), path, 0)),
    ("method, 0 + path",
     lambda: disp.InvokeTypes(dispid, 0, M, (VARIANT, 0), ((I4, 1), (BSTR, 1)), 0, path)),
    ("method, path + path",
     lambda: disp.InvokeTypes(dispid, 0, M, (VARIANT, 0), ((BSTR, 1), (BSTR, 1)), path, path)),
]

worked = None
for label, call in FORMS:
    print(f"\nTrying: {label} ...")
    try:
        ret = call()
        print(f"  ACCEPTED, returned {ret!r}")
        worked = label
        break
    except pythoncom.com_error as ex:
        print(f"  rejected: {ex.args[1] if len(ex.args) > 1 else ex}")

print("\n" + ("=" * 60))
print(f"RESULT: {worked or 'no form accepted'}")
print("=" * 60)
if worked:
    print("\nLook at DNC now:")
    print("  1. Did a DNC window appear?")
    print("  2. Is the file loaded and ready to send?")
    print("  3. Did it start sending on its own?")
input("\nPress Enter to let go of DNC (then watch whether DNC stays open) ...")
del disp
time.sleep(3)
print("Released. Is DNC still open? Report what you saw, with the RESULT line.")
