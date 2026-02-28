from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.addons.discovery import repo_root


@dataclass
class CatalogQuery:
    q: str | None = None
    category: str | None = None
    featured: bool | None = None
    sort: str = "recent"
    page: int = 1
    page_size: int = 20


class StaticCatalogStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._last_successful_load: str | None = None

    @classmethod
    def from_default_path(cls) -> "StaticCatalogStore":
        return cls(repo_root() / "backend" / "app" / "store" / "catalog.json")

    def _load_items(self) -> tuple[list[dict[str, Any]], str | None]:
        if not self.path.exists():
            return [], "catalog_file_missing"
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return [], "catalog_json_must_be_array"
            out: list[dict[str, Any]] = []
            for raw in data:
                if isinstance(raw, dict):
                    out.append(raw)
            self._last_successful_load = datetime.now(timezone.utc).isoformat()
            return out, None
        except Exception:
            return [], "catalog_read_or_parse_error"

    def query(self, req: CatalogQuery) -> dict[str, Any]:
        items, load_error = self._load_items()

        q = (req.q or "").strip().lower()
        category = (req.category or "").strip().lower()

        filtered: list[dict[str, Any]] = []
        for item in items:
            if q:
                search_blob = " ".join(
                    [
                        str(item.get("id", "")),
                        str(item.get("name", "")),
                        str(item.get("description", "")),
                        " ".join(str(x) for x in item.get("categories", []) if isinstance(x, str)),
                    ]
                ).lower()
                if q not in search_blob:
                    continue

            if category:
                categories = [str(x).strip().lower() for x in item.get("categories", []) if str(x).strip()]
                if category not in categories:
                    continue

            if req.featured is not None and bool(item.get("featured", False)) != req.featured:
                continue

            filtered.append(item)

        sort = req.sort.strip().lower()
        if sort == "recent":
            filtered.sort(key=lambda x: str(x.get("published_at", "")), reverse=True)
        elif sort == "name":
            filtered.sort(key=lambda x: str(x.get("name", "")).lower())
        else:
            filtered.sort(key=lambda x: str(x.get("id", "")).lower())

        page = max(1, int(req.page))
        page_size = max(1, min(100, int(req.page_size)))
        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = filtered[start:end]

        categories = sorted(
            {
                str(cat).strip()
                for item in items
                for cat in item.get("categories", [])
                if str(cat).strip()
            }
        )

        return {
            "ok": True,
            "items": page_items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_next": end < total,
            "sort": sort,
            "filters": {
                "q": req.q,
                "category": req.category,
                "featured": req.featured,
            },
            "categories": categories,
            "catalog_status": {
                "status": "error" if load_error else "ok",
                "message": load_error,
                "last_successful_load": self._last_successful_load,
            },
        }
