"""Loads the downloaded Blender 4.1 manual pages into Azure AI Search (index `blender-manual`, SRS 9).

Run scripts/fetch_manual.py first. Manual text is CC BY-SA 4.0, credit "Blender Documentation Team".
Sends text only. Needs AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY (and AZURE_SEARCH_INDEX) in .env.
Usage: python scripts/build_docs_index.py [--dry-run]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pathlit.brain.manual import parse_rst  # noqa: E402
from pathlit.config import env  # noqa: E402


def load_docs(folder: Path):
    docs = []
    for p in sorted(folder.glob("*.rst")):
        docs += parse_rst(p.read_text(encoding="utf-8", errors="replace"), p.stem)
    return docs


def main() -> None:
    folder = ROOT / "data" / "manual_4.1"
    docs = load_docs(folder)
    total_kb = sum(len(d.content) for d in docs) / 1024
    print(f"{len(docs)} sections from {len(list(folder.glob('*.rst')))} pages, {total_kb:.0f} KB of text")
    if "--dry-run" in sys.argv or not docs:
        for d in docs[:5]:
            print(f"- {d.title} / {d.section}: {d.content[:90]!r}")
        return

    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import SearchableField, SearchFieldDataType, SearchIndex, SimpleField

    endpoint, key, name = env("AZURE_SEARCH_ENDPOINT"), env("AZURE_SEARCH_KEY"), env("AZURE_SEARCH_INDEX", "blender-manual")
    if not endpoint or not key:
        sys.exit("Set AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY in .env first.")
    cred = AzureKeyCredential(key)
    index = SearchIndex(name=name, fields=[
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="title", type=SearchFieldDataType.String),
        SearchableField(name="section", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String),
    ])
    SearchIndexClient(endpoint, cred).create_or_update_index(index)
    client = SearchClient(endpoint, name, cred)
    rows = [{"id": d.id, "title": d.title, "section": d.section, "content": d.content} for d in docs]
    for i in range(0, len(rows), 100):
        res = client.upload_documents(rows[i:i + 100])
        print(f"uploaded {sum(r.succeeded for r in res)}/{len(res)}")


if __name__ == "__main__":
    main()
