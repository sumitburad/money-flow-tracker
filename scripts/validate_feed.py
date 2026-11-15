"""Validate a versioned feed before any publication or downstream ingestion."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.feed_contract import load_feed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/validate_feed.py path/to/feed.json")
    feed = load_feed(sys.argv[1])
    print(f"Validated schema {feed['schema_version']}: {len(feed['items'])} items")
