"""Smoke test: the project is set up and run.py runs. No accounting is tested here."""

import run


def test_run_py_finishes_and_folders_exist(capsys):
    run.main()

    output = capsys.readouterr().out
    assert "January-March 2026" in output
    for folder in run.FOLDERS:
        assert (run.ROOT / folder).is_dir()
