from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

TOKEN_RE = re.compile(r"[^\W_]+(?:[_'-][^\W_]+)*", re.UNICODE)


class DanbooruWiki:
    """Read-only FTS5 search over the isek-ai/danbooru-wiki-2024 snapshot.

    Ported from the sibling style-genome-explorer project (same DB, CC BY-SA 4.0
    upstream — see data/DANBOORU_WIKI_LICENSE.md).
    """

    def __init__(self, path: Path):
        self.path = path

    def search(self, query: str, category: str = "", limit: int = 20) -> list[dict]:
        tokens = TOKEN_RE.findall(query.casefold().replace("_", " "))
        if not tokens:
            return []
        expression = " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        category_clause = "AND p.category = ?" if category else ""
        params = [expression, *([category] if category else []), limit]
        rows = db.execute(
            "SELECT p.tag,p.title,p.aliases,p.category,substr(replace(p.body,char(10),' '),1,280) snippet "
            "FROM pages_fts JOIN pages p ON p.id=pages_fts.rowid "
            f"WHERE pages_fts MATCH ? {category_clause} ORDER BY bm25(pages_fts,12,8,4,1) LIMIT ?",
            params,
        ).fetchall()
        db.close()
        return [
            {"tag": r["tag"], "title": r["title"], "aliases": json.loads(r["aliases"]), "category": r["category"], "snippet": r["snippet"]}
            for r in rows
        ]

    def lookup_exact(self, candidate: str) -> dict | None:
        normalized = candidate.casefold().replace("_", " ").strip()
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT tag,category,title,aliases FROM pages WHERE lower(replace(tag,'_',' '))=? LIMIT 1",
                (normalized,),
            ).fetchone()
        if not row:
            return None
        return {"tag": row["tag"], "category": row["category"], "title": row["title"], "aliases": json.loads(row["aliases"])}

    def resolve_artist(self, candidate: str) -> str | None:
        norm = candidate.casefold().replace("_", " ").strip()
        norm = re.sub(r"^(?:artist|by)\s*[:\s]\s*", "", norm).strip()
        if not norm:
            return None

        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT tag FROM pages WHERE category='artist' AND lower(replace(tag, '_', ' ')) = ? LIMIT 1",
                (norm,),
            ).fetchone()
            if row:
                return row["tag"]

            parts = norm.split()
            if len(parts) == 2:
                reversed_name = f"{parts[1]} {parts[0]}"
                row = db.execute(
                    "SELECT tag FROM pages WHERE category='artist' AND lower(replace(tag, '_', ' ')) = ? LIMIT 1",
                    (reversed_name,),
                ).fetchone()
                if row:
                    return row["tag"]

            row = db.execute(
                "SELECT tag FROM pages WHERE category='artist' AND aliases LIKE ? LIMIT 1",
                (f'%"{norm}"%',),
            ).fetchone()
            if row:
                return row["tag"]

            row = db.execute(
                "SELECT tag FROM pages WHERE lower(replace(tag, '_', ' ')) = ? LIMIT 1",
                (f"{norm} (style)",),
            ).fetchone()
            if row:
                return row["tag"].removesuffix(" (style)")

        for row in self.search(norm, "artist", 8):
            names = [row["tag"], *row["aliases"]]
            if any(name.casefold().replace("_", " ").strip() == norm for name in names):
                return row["tag"]
        return None
