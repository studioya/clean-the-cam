import json
import sys
import types

import pytest

from clean_the_cam import dnc, settings


class FakeDisp:
    def GetIDsOfNames(self, name):
        assert name == 'LoadFile'
        return 3

    def InvokeTypes(self, dispid, lcid, flags, rettype, argtypes, *args):
        assert dispid == 3 and argtypes == ((8 | 0x4000, 3),)   # BSTR by reference
        FakeDnc.loaded.append(args[0])


class FakeDnc:
    loaded = []

    def __init__(self):
        self._oleobj_ = FakeDisp()


@pytest.fixture
def fake_com(monkeypatch):
    calls = []

    def Dispatch(progid):
        calls.append(progid)
        if progid != 'DNC.Document':
            raise RuntimeError('class not registered')
        return FakeDnc()

    client = types.SimpleNamespace(Dispatch=Dispatch)
    monkeypatch.setitem(sys.modules, 'win32com', types.SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, 'win32com.client', client)
    monkeypatch.setitem(sys.modules, 'pythoncom', types.SimpleNamespace(
        DISPATCH_METHOD=1, VT_VARIANT=12, VT_BSTR=8, VT_BYREF=0x4000))
    monkeypatch.setattr(dnc, 'show_dnc', lambda exe, timeout=5.0: True)
    FakeDnc.loaded = []
    return calls


def test_loads_via_automation(tmp_path, fake_com):
    f = tmp_path / 'p_clean.ENC'
    f.write_text('%\n')
    msg, automatic = dnc.load_into_dnc(str(f), settings.DEFAULTS)
    assert automatic
    assert FakeDnc.loaded == [str(f)]
    assert fake_com == ['DNC.Document']
    assert 'transfer to the machine started' in msg


def test_falls_back_to_opening_dnc(tmp_path, fake_com, monkeypatch):
    f = tmp_path / 'p_clean.ENC'
    f.write_text('%\n')
    exe = tmp_path / 'DNC2000.exe'
    exe.write_text('')
    started = []
    monkeypatch.setattr(dnc.subprocess, 'Popen', lambda args, cwd=None: started.append(args))
    cfg = dict(settings.DEFAULTS, dnc_progid='Wrong.Name', dnc_exe=str(exe))
    msg, automatic = dnc.load_into_dnc(str(f), cfg)
    assert not automatic
    assert started == [[str(exe)]]
    assert 'Automatic loading failed' in msg and 'clipboard' in msg


def test_missing_output_file(tmp_path):
    with pytest.raises(dnc.DncError):
        dnc.load_into_dnc(str(tmp_path / 'nope.ENC'), settings.DEFAULTS)


def test_old_empty_dnc_settings_get_the_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path))
    p = settings.path()
    (tmp_path / 'CleanTheCAM').mkdir()
    with open(p, 'w') as f:
        json.dump({'dnc_progid': '', 'dnc_method': '', 'home': 'keep'}, f)
    s = settings.load()
    assert s['dnc_progid'] == 'DNC.Document' and s['dnc_method'] == 'LoadFile'
    assert s['home'] == 'keep'
