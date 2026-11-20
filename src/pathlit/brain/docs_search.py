"""Azure AI Search lookup of the Blender manual (FR-12). Failure or missing keys give an empty list, never a crash."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from ..config import env

log = logging.getLogger(__name__)
SNIPPET_CHARS = 600


@dataclass
class Snippet:
    title: str          # manual page title, kept so answers can name their source
    section: str
    content: str


class DocsSearch(Protocol):
    def lookup(self, query: str, top: int = 3) -> list[Snippet]: ...


class NullDocsSearch:
    """Used when Azure AI Search is not configured. The lesson simply runs without manual excerpts."""

    def lookup(self, query: str, top: int = 3) -> list[Snippet]:
        return []


class AzureDocsSearch:
    def __init__(self, endpoint: str, key: str, index: str) -> None:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient

        self._client = SearchClient(endpoint, index, AzureKeyCredential(key))

    def lookup(self, query: str, top: int = 3) -> list[Snippet]:
        try:
            results = self._client.search(search_text=query, top=top, select=["title", "section", "content"])
            return [Snippet(r["title"], r["section"], r["content"][:SNIPPET_CHARS]) for r in results]
        except Exception as e:
            log.warning("docs search failed: %s", str(e)[:200])
            return []


def make_docs_search() -> DocsSearch:
    endpoint, key, index = env("AZURE_SEARCH_ENDPOINT"), env("AZURE_SEARCH_KEY"), env("AZURE_SEARCH_INDEX", "blender-manual")
    if endpoint and key:
        return AzureDocsSearch(endpoint, key, index)
    log.info("Azure AI Search not configured; running without manual excerpts")
    return NullDocsSearch()
