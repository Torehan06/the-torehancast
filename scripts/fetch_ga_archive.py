"""Download every county document for one or more Georgia election codes."""
import sys
from pathlib import Path

from torehancast.adapters import ga_enhanced_voting as ga
from torehancast.http import PoliteClient

client = PoliteClient()
for code in sys.argv[1:]:
    out = Path("data/archives/GA") / code
    if out.exists() and len(list(out.glob("*.json"))) >= 159:
        print(code, "already archived")
        continue
    docs = ga.fetch_all(client, code)
    ga.save_archive(docs, out)
    print(code, len(docs), "county files")
