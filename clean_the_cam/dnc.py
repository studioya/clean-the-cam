"""
Hand a finished program to Metalix DNC for transfer to the machine.

cncKad's simulator starts DNC as an automation server ("DNC2000.exe
-Embedding") and calls DNC.Document.LoadFile with the path. DNC takes the path
BY REFERENCE (a plain text argument gives "Type mismatch") and starts the
transfer to the machine straight away, as it does from cncKad. A server started
this way is hidden, so its window is shown afterwards; DNC stays open after
Clean The CAM lets go of it (tested on the shop PC, DNC 19.2.350). If any of
that fails, DNC is opened normally with the output path on the clipboard.
"""

import os
import subprocess
import time


class DncError(Exception):
    pass


def _load(progid, method, path):
    import pythoncom
    import win32com.client
    obj = win32com.client.Dispatch(progid)
    disp = obj._oleobj_
    dispid = disp.GetIDsOfNames(method)
    # path by reference (what DNC accepts)
    disp.InvokeTypes(dispid, 0, pythoncom.DISPATCH_METHOD, (pythoncom.VT_VARIANT, 0),
                     ((pythoncom.VT_BSTR | pythoncom.VT_BYREF, 3),), path)
    return obj


def _dnc_windows(exe):
    """Top-level windows owned by the DNC program, titled ones first."""
    import win32api
    import win32gui
    import win32process
    want = os.path.basename(exe).lower()
    found = []

    def cb(h, _):
        if win32gui.GetParent(h):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(h)
            hp = win32api.OpenProcess(0x0410, False, pid)   # query + read
            try:
                name = win32process.GetModuleFileNameEx(hp, 0)
            finally:
                win32api.CloseHandle(hp)
        except Exception:
            return True
        if os.path.basename(name).lower() == want:
            found.append((win32gui.GetWindowText(h), h))
        return True

    win32gui.EnumWindows(cb, None)
    return [h for t, h in sorted(found, key=lambda th: (not th[0].upper().startswith('DNC'), th[0]))
            if t]


def show_dnc(exe, timeout=5.0):
    """Bring DNC's main window up. Returns True if one was shown."""
    try:
        import win32con
        import win32gui
    except ImportError:
        return False
    end = time.time() + timeout
    while True:
        wins = _dnc_windows(exe)
        if wins or time.time() > end:
            break
        time.sleep(0.25)
    if not wins:
        return False
    h = wins[0]
    win32gui.ShowWindow(h, win32con.SW_SHOW)
    if win32gui.IsIconic(h):
        win32gui.ShowWindow(h, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(h)
    except Exception:
        pass        # Windows may refuse focus stealing; the window is still shown
    return True


def load_into_dnc(path, settings):
    """Returns (message, used_automation). Raises DncError on failure."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise DncError(f"Output file not found:\n{path}")
    progid = (settings.get('dnc_progid') or '').strip()
    method = (settings.get('dnc_method') or '').strip()
    exe = (settings.get('dnc_exe') or '').strip()
    problem = None
    if progid and method:
        try:
            _load(progid, method, path)
            shown = show_dnc(exe or 'DNC2000.exe')
            msg = f"Sent to DNC - transfer to the machine started:\n{os.path.basename(path)}"
            if not shown:
                msg += "\n\n(DNC's window could not be brought up - check the taskbar.)"
            return (msg, True)
        except ImportError:
            problem = "pywin32 is not available in this build"
        except Exception as ex:  # COM errors come in many shapes
            problem = f"{progid}.{method} failed: {ex}"
    if not exe or not os.path.isfile(exe):
        raise DncError((f"{problem}\n\n" if problem else "") +
                       f"DNC program not found:\n{exe or '(not set)'}\n\n"
                       f"Set its location under Settings.")
    try:
        subprocess.Popen([exe], cwd=os.path.dirname(exe))
    except OSError as ex:
        raise DncError(f"Could not start DNC:\n{ex}")
    lead = f"Automatic loading failed ({problem}).\n\n" if problem else ""
    return (lead + "DNC opened. The output path is on the clipboard -\n"
            "paste it into DNC's open dialog:\n\n" + path, False)
