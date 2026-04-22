from pathlib import Path
from types import SimpleNamespace

import pytest

from marimapper.file_tools import (
    find_view_csvs,
    archive_existing_scans,
)
from marimapper.scripts.scanner_cli import _handle_existing_scans


def _write_view_csv(path: Path, rows: list[tuple[int, float, float]]) -> None:
    lines = ["index,u,v"]
    for idx, u, v in rows:
        lines.append(f"{idx},{u:f},{v:f}")
    path.write_text("\n".join(lines))


def test_find_view_csvs_returns_only_valid_view_maps(tmp_path):
    _write_view_csv(tmp_path / "0.csv", [(0, 0.1, 0.2), (1, 0.3, 0.4)])
    _write_view_csv(tmp_path / "1.csv", [(0, 0.1, 0.2)])
    # Not a view CSV — different header
    (tmp_path / "led_map_3d.csv").write_text(
        "index,x,y,z,xn,yn,zn,error\n0,0,0,0,0,0,0,0"
    )
    # Not a CSV
    (tmp_path / "notes.txt").write_text("hello")

    found = sorted(p.name for p in find_view_csvs(tmp_path))
    assert found == ["0.csv", "1.csv"]


def test_archive_existing_scans_moves_views_into_timestamped_subdir(tmp_path):
    _write_view_csv(tmp_path / "0.csv", [(0, 0.1, 0.2)])
    _write_view_csv(tmp_path / "1.csv", [(0, 0.3, 0.4)])
    # Preserve a 3D map file so we can verify the archive is scoped to views
    (tmp_path / "led_map_3d.csv").write_text(
        "index,x,y,z,xn,yn,zn,error\n0,0,0,0,0,0,0,0"
    )

    archive_dir = archive_existing_scans(tmp_path)

    assert archive_dir.exists()
    assert archive_dir.parent == tmp_path
    assert archive_dir.name.startswith("archived_")

    # View CSVs moved
    assert (archive_dir / "0.csv").exists()
    assert (archive_dir / "1.csv").exists()
    assert not (tmp_path / "0.csv").exists()
    assert not (tmp_path / "1.csv").exists()

    # 3D map left untouched in main dir
    assert (tmp_path / "led_map_3d.csv").exists()


def test_archive_existing_scans_noop_when_no_views(tmp_path):
    # No view CSVs — archive should return None, not create an empty dir.
    archive_dir = archive_existing_scans(tmp_path)
    assert archive_dir is None
    assert list(tmp_path.iterdir()) == []


def test_handle_existing_scans_noop_when_empty(tmp_path):
    args = SimpleNamespace(dir=tmp_path, resume=False, fresh=False)
    # Should not prompt, should not raise.
    _handle_existing_scans(args)


def test_handle_existing_scans_resume_flag_keeps_views(tmp_path, capsys):
    _write_view_csv(tmp_path / "0.csv", [(0, 0.1, 0.2)])
    args = SimpleNamespace(dir=tmp_path, resume=True, fresh=False)
    _handle_existing_scans(args)
    assert (tmp_path / "0.csv").exists()
    assert "Resuming" in capsys.readouterr().out


def test_handle_existing_scans_fresh_flag_archives(tmp_path):
    _write_view_csv(tmp_path / "0.csv", [(0, 0.1, 0.2)])
    args = SimpleNamespace(dir=tmp_path, resume=False, fresh=True)
    _handle_existing_scans(args)
    assert not (tmp_path / "0.csv").exists()
    archives = [p for p in tmp_path.iterdir() if p.name.startswith("archived_")]
    assert len(archives) == 1
    assert (archives[0] / "0.csv").exists()


def test_handle_existing_scans_rejects_both_flags(tmp_path):
    _write_view_csv(tmp_path / "0.csv", [(0, 0.1, 0.2)])
    args = SimpleNamespace(dir=tmp_path, resume=True, fresh=True)
    with pytest.raises(Exception, match="mutually exclusive"):
        _handle_existing_scans(args)
