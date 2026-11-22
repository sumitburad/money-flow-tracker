import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "sync_site", Path(__file__).resolve().parent.parent / "scripts" / "sync_site.py")
sync_site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_site)


def test_history_is_mirrored_and_stale_files_are_removed(tmp_path):
    source = tmp_path / "data" / "history" / "v1"
    (source / "fred").mkdir(parents=True)
    (source / "fred" / "DGS2.csv").write_text("a\n")
    (source / "manifest.json").write_text("{}\n")
    stale = tmp_path / "docs" / "history" / "v1" / "fred" / "OLD.csv"
    stale.parent.mkdir(parents=True)
    stale.write_text("old\n")

    assert sync_site.sync_history(tmp_path) == 4  # 2 files x 2 website folders
    for folder in ("docs", "frontend"):
        base = tmp_path / folder / "history" / "v1"
        assert (base / "fred" / "DGS2.csv").read_text() == "a\n"
        assert (base / "manifest.json").is_file()
    assert not stale.exists()


def test_no_history_means_nothing_to_do(tmp_path):
    assert sync_site.sync_history(tmp_path) == 0
