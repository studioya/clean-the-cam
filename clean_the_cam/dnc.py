"""
Hand a finished program to Metalix DNC for transfer to the machine.

cncKad's simulator starts DNC as an automation server ("DNC2000.exe
-Embedding") and calls DNC.Document.LoadFile(path). Clean The CAM does the
same. If that fails it falls back to opening DNC normally with the output
path on the clipboard.
"""

import os
import subprocess


class DncError(Exception):
    pass


# DNC runs as an automation server: it may close as soon as the last
# reference to it is released, so the one we create is kept alive here.
_live = None


def load_into_dnc(path, settings):
    """Returns (message, used_automation). Raises DncError on failure."""
    global _live
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise DncError(f"Output file not found:\n{path}")
    progid = (settings.get('dnc_progid') or '').strip()
    method = (settings.get('dnc_method') or '').strip()
    problem = None
    if progid and method:
        try:
            import win32com.client  # pywin32, only present in the Windows build
            dnc = win32com.client.Dispatch(progid)
            getattr(dnc, method)(path)
            _live = dnc
            return (f"Loaded into DNC:\n{os.path.basename(path)}", True)
        except ImportError:
            problem = "pywin32 is not available in this build"
        except Exception as ex:  # COM errors come in many shapes
            problem = f"{progid}.{method} failed: {ex}"
    exe = (settings.get('dnc_exe') or '').strip()
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
