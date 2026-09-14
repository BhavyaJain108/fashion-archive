import pytest

import backend.archive.runner.cli as cli
from config.config import config


@pytest.mark.unit
def test_daemon_start_refuses_to_run_blind(tmp_path, monkeypatch, capsys):
    """A missing credential used to be silent: the store fell back to a directory in
    the container and the daemon slept for ever, having written nothing to R2."""
    for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_BUCKET"):
        monkeypatch.setattr(config, name, "", raising=False)

    brands = tmp_path / "brands.yml"
    brands.write_text("brands: []\n")

    assert cli.main(["daemon", "start", "--brands", str(brands)]) == 2
    assert "refusing to start" in capsys.readouterr().err
