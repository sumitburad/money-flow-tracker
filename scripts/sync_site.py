"""Publish the same static dashboard to GitHub Pages /docs and existing /frontend host.

No private data leaves the repository. Only the already-vetted public feed and the
official-source history files are copied.
"""
from pathlib import Path
from shutil import copyfile, rmtree

ROOT = Path(__file__).resolve().parent.parent
FILES = (
    ("docs/index.html", "frontend/index.html"),
    ("docs/status.json", "frontend/status.json"),
    ("docs/feed/v1/latest.json", "frontend/feed/v1/latest.json"),
)
# data/history/v1 is where the history loader writes; the dashboard reads the copies.
HISTORY_SOURCE = "data/history/v1"
HISTORY_COPIES = ("docs/history/v1", "frontend/history/v1")


def sync_history(root=ROOT):
    """Mirror the history folder into the website folders. Returns files copied."""
    source = Path(root) / HISTORY_SOURCE
    if not source.is_dir():
        return 0
    copied = 0
    for target in HISTORY_COPIES:
        destination = Path(root) / target
        if destination.exists():
            rmtree(destination)  # drop files of series that no longer exist
        for item in sorted(source.rglob("*")):
            if item.is_file():
                out = destination / item.relative_to(source)
                out.parent.mkdir(parents=True, exist_ok=True)
                copyfile(item, out)
                copied += 1
    return copied


def main():
    for source, destination in FILES:
        src, dst = ROOT / source, ROOT / destination
        if not src.is_file():
            raise FileNotFoundError(str(src))
        dst.parent.mkdir(parents=True, exist_ok=True)
        copyfile(src, dst)
        print("Synced", destination)
    count = sync_history()
    if count:
        print("Synced %d history files" % count)


if __name__ == "__main__":
    main()
