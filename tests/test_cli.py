import os
import shutil

from clean_the_cam import cli

HERE = os.path.dirname(__file__)


def test_folder_batch(tmp_path, capsys):
    for n in ('pomegranate.ENC', 'pomegranate_nohatch.ENC'):
        shutil.copy(os.path.join(HERE, 'samples', n), tmp_path / n)
    code = cli.main([str(tmp_path), '--home', 'bottom-left', '--end', 'home'])
    assert code == 1                                  # warnings, no failures
    assert (tmp_path / 'pomegranate_clean.ENC').exists()
    assert (tmp_path / 'pomegranate_nohatch_clean_report.txt').exists()
    out = (tmp_path / 'pomegranate_clean.ENC').read_text()
    assert 'G92 X10. Y10.' in out and out.rstrip().endswith('G50\n%')
    assert 'use --cleanup yes' in capsys.readouterr().out

    # a second run skips the _clean outputs, and refuses one given directly
    assert cli.main([str(tmp_path / 'pomegranate_clean.ENC')]) == 2


def test_custom_xy_and_dry_run(tmp_path):
    shutil.copy(os.path.join(HERE, 'samples', 'pomegranate.ENC'), tmp_path / 'p.ENC')
    assert cli.main([str(tmp_path / 'p.ENC'), '--end', '100,50.5', '--dry-run']) == 1
    assert not (tmp_path / 'p_clean.ENC').exists()
