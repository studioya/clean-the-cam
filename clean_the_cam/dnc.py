"""
Hand a finished program to Metalix DNC for transfer to the machine.

cncKad starts DNC as an automation (COM) server ("DNC2000.exe -Embedding") and
tells it which file to load. When the automation name (ProgID) and the method
that loads a file are known, Clean The CAM does the same. Until then it opens
DNC normally and puts the output path on the clipboard to paste in.

Nothing here ever starts a transfer - the send stays a button pressed in DNC.
"""

import os
import subprocess


class DncError(Exception):
    pass


def load_into_dnc(path, settings):
    """Returns a short message for the user. Raises DncError on failure."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise DncError(f"Output file not found:\n{path}")
    progid = (settings.get('dnc_progid') or '').strip()
    method = (settings.get('dnc_method') or '').strip()
    if progid and method:
        try:
            import win32com.client  # pywin32, only present in the Windows build
        except ImportError:
            raise DncError("DNC automation is configured but pywin32 is not available "
                           "in this build.")
        try:
            dnc = win32com.client.Dispatch(progid)
            getattr(dnc, method)(path)
        except Exception as ex:  # COM errors come in many shapes
            raise DncError(f"DNC refused the file via {progid}.{method}:\n{ex}")
        return f"Loaded into DNC:\n{os.path.basename(path)}\n\nPress send in DNC when ready."
    exe = (settings.get('dnc_exe') or '').strip()
    if not exe or not os.path.isfile(exe):
        raise DncError(f"DNC program not found:\n{exe or '(not set)'}\n\n"
                       f"Set its location under Settings.")
    try:
        subprocess.Popen([exe], cwd=os.path.dirname(exe))
    except OSError as ex:
        raise DncError(f"Could not start DNC:\n{ex}")
    return ("DNC opened. The output path is on the clipboard -\n"
            "paste it into DNC's open dialog:\n\n" + path)
