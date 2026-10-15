"""
List what Metalix DNC exposes to automation, so Clean The CAM can load files
into it the way cncKad does.

    python tools\\dnc_probe.py                  (uses DNC.Document)
    python tools\\dnc_probe.py OtherProgID

Needs pywin32 (build_exe.bat installs it, or: python -m pip install pywin32).
Read-only: it starts DNC as cncKad does, lists the methods and properties,
and calls nothing. Paste the whole output back.
"""

import glob
import os
import sys

try:
    import pythoncom
    import win32api
    import win32com.client
    import winreg
except ImportError:
    sys.exit("pywin32 is missing:  python -m pip install pywin32")

PROGID = sys.argv[1] if len(sys.argv) > 1 else "DNC.Document"
KIND = {1: "method", 2: "property get", 4: "property put", 8: "property putref"}


def dump_typeinfo(ti, label):
    ta = ti.GetTypeAttr()
    name = ti.GetDocumentation(-1)[0]
    print(f"\n--- {label}: {name}  ({ta.cFuncs} functions, {ta.cVars} properties)")
    for n in range(ta.cFuncs):
        fd = ti.GetFuncDesc(n)
        names = ti.GetNames(fd.memid, fd.cParams + 1)
        print(f"  {KIND.get(fd.invkind, fd.invkind):<15} {names[0]}({', '.join(names[1:])})"
              f"   [id {fd.memid}]")
    for n in range(ta.cVars):
        vd = ti.GetVarDesc(n)
        print(f"  {'property':<15} {ti.GetNames(vd.memid)[0]}   [id {vd.memid}]")


def dump_typelib(tl, label):
    print(f"\n=== type library {label}: {tl.GetDocumentation(-1)[0]}")
    for n in range(tl.GetTypeInfoCount()):
        try:
            dump_typeinfo(tl.GetTypeInfo(n), f"type {n}")
        except pythoncom.com_error as ex:
            print(f"  type {n}: {ex}")


def reg(path, value=""):
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, path) as k:
            return winreg.QueryValueEx(k, value)[0]
    except OSError:
        return None


print(f"ProgID      {PROGID}")
clsid = reg(f"{PROGID}\\CLSID")
print(f"CLSID       {clsid}")
server = None
if clsid:
    for root in ("CLSID", "WOW6432Node\\CLSID"):
        server = server or reg(f"{root}\\{clsid}\\LocalServer32")
        tlid = reg(f"{root}\\{clsid}\\TypeLib")
        if tlid:
            print(f"TypeLib     {tlid}")
print(f"Server      {server}")

found = False

# 1. ask the running object for its own type information
try:
    obj = win32com.client.Dispatch(PROGID)
    ti = obj._oleobj_.GetTypeInfo()
    dump_typeinfo(ti, "from the object")
    found = True
except pythoncom.com_error as ex:
    print(f"\n(object gives no type info: {ex})")

# 2. a type library embedded in the exe, or .tlb files next to it
candidates = []
if server:
    exe = server.split(" -")[0].strip().strip('"')
    candidates.append(exe)
    candidates += glob.glob(os.path.join(os.path.dirname(exe), "*.tlb"))
candidates += glob.glob(r"C:\Metalix\DNC.19\*.tlb")
for path in dict.fromkeys(candidates):
    try:
        dump_typelib(pythoncom.LoadTypeLib(path), path)
        found = True
    except pythoncom.com_error as ex:
        print(f"\n(no type library in {path}: {ex})")

if not found:
    print("\nNothing readable found. Please also send a screenshot of DNC's own Help/About.")

print("\nDone. DNC may still be running in the background - close it from Task Manager "
      "if it doesn't close by itself.")
