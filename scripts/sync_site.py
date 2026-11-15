"""Publish the same static dashboard to GitHub Pages /docs and existing /frontend host.

No private data leaves the repository. Only the already-vetted public feed is copied.
"""
from pathlib import Path
from shutil import copyfile

ROOT = Path(__file__).resolve().parent.parent
FILES = (
    ("docs/index.html", "frontend/index.html"),
    ("docs/status.json", "frontend/status.json"),
    ("docs/feed/v1/latest.json", "frontend/feed/v1/latest.json"),
)


def main():
    for source, destination in FILES:
        src, dst = ROOT / source, ROOT / destination
        if not src.is_file():
            raise FileNotFoundError(str(src))
        dst.parent.mkdir(parents=True, exist_ok=True)
        copyfile(src, dst)
        print("Synced", destination)


if __name__ == "__main__":
    main()
