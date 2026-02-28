from __future__ import annotations

import json
import os
import shutil
import tempfile
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.addons.discovery import repo_root
from .sources import OFFICIAL_SOURCE_ID, StoreSource


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


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_int(name: str, default: int, min_value: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(min_value, int(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float, min_value: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(min_value, float(raw))
    except ValueError:
        return default


def _safe_json_load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        return {}
    return {}


def _load_catalog_public_keys(path: Path | None, inline_json: str | None) -> list[str]:
    keys: list[str] = []

    def _append_from_obj(obj: Any) -> None:
        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, str) and item.strip():
                    keys.append(item.strip())
                elif isinstance(item, dict):
                    if item.get("enabled", True) is False:
                        continue
                    pem = item.get("pem")
                    if isinstance(pem, str) and pem.strip():
                        keys.append(pem.strip())
        elif isinstance(obj, dict):
            _append_from_obj(obj.get("keys"))

    if inline_json and inline_json.strip():
        try:
            _append_from_obj(json.loads(inline_json))
        except Exception:
            pass

    if path is not None and path.exists():
        try:
            _append_from_obj(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass

    deduped: list[str] = []
    seen = set()
    for pem in keys:
        if pem in seen:
            continue
        deduped.append(pem)
        seen.add(pem)
    return deduped


def _verify_detached_signature(payload: bytes, signature_bytes: bytes, public_keys_pem: list[str]) -> None:
    if not public_keys_pem:
        raise RuntimeError("catalog_store_public_keys_missing")
    if not signature_bytes or not signature_bytes.strip():
        raise RuntimeError("catalog_signature_missing")

    try:
        signature = base64.b64decode(signature_bytes.strip(), validate=True)
    except Exception as exc:
        raise RuntimeError("catalog_signature_invalid_encoding") from exc

    for pem in public_keys_pem:
        try:
            key = serialization.load_pem_public_key(pem.encode("utf-8"))
            if not isinstance(key, rsa.RSAPublicKey):
                continue
            key.verify(signature, payload, padding.PKCS1v15(), hashes.SHA256())
            return
        except InvalidSignature:
            continue
        except Exception:
            continue
    raise RuntimeError("catalog_signature_invalid")


def _verify_catalog_signatures(
    index_bytes: bytes,
    index_sig_bytes: bytes,
    publishers_bytes: bytes,
    publishers_sig_bytes: bytes,
    public_keys_pem: list[str],
) -> None:
    if not index_bytes:
        raise RuntimeError("catalog_index_empty")
    if not publishers_bytes:
        raise RuntimeError("catalog_publishers_empty")
    if not index_sig_bytes or not index_sig_bytes.strip():
        raise RuntimeError("catalog_index_signature_missing")
    if not publishers_sig_bytes or not publishers_sig_bytes.strip():
        raise RuntimeError("catalog_publishers_signature_missing")
    _verify_detached_signature(index_bytes, index_sig_bytes, public_keys_pem)
    _verify_detached_signature(publishers_bytes, publishers_sig_bytes, public_keys_pem)


class CatalogCacheClient:
    REQUIRED_FILES = (
        "catalog/v1/index.json",
        "catalog/v1/index.json.sig",
        "catalog/v1/publishers.json",
        "catalog/v1/publishers.json.sig",
    )

    def __init__(
        self,
        cache_root: Path,
        *,
        timeout_s: float | None = None,
        max_bytes: int | None = None,
        max_redirects: int | None = None,
        catalog_public_keys_path: Path | None = None,
        catalog_public_keys_json: str | None = None,
    ) -> None:
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s if timeout_s is not None else _env_float("STORE_CATALOG_TIMEOUT_S", 12.0, min_value=1.0)
        self.max_bytes = max_bytes if max_bytes is not None else _env_int("STORE_CATALOG_MAX_BYTES", 5_000_000, min_value=1024)
        self.max_redirects = (
            max_redirects if max_redirects is not None else _env_int("STORE_CATALOG_MAX_REDIRECTS", 3, min_value=0)
        )
        if catalog_public_keys_path is None:
            catalog_public_keys_path = Path(os.getenv("STORE_CATALOG_PUBLIC_KEYS_PATH", "var/store_catalog_public_keys.json"))
        self.catalog_public_keys = _load_catalog_public_keys(catalog_public_keys_path, catalog_public_keys_json or os.getenv("STORE_CATALOG_PUBLIC_KEYS_JSON"))

    @classmethod
    def from_default_path(cls) -> "CatalogCacheClient":
        return cls(repo_root() / "runtime" / "store" / "cache")

    def _source_dir(self, source_id: str) -> Path:
        return self.cache_root / source_id

    def _metadata_path(self, source_id: str) -> Path:
        return self._source_dir(source_id) / "metadata.json"

    def _download_bytes(self, url: str) -> bytes:
        timeout = httpx.Timeout(self.timeout_s)
        current = url
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            for _ in range(self.max_redirects + 1):
                with client.stream("GET", current, headers={"Accept": "application/json"}) as resp:
                    if resp.status_code in {301, 302, 303, 307, 308}:
                        location = resp.headers.get("location")
                        if not location:
                            raise RuntimeError("catalog_redirect_missing_location")
                        candidate = urljoin(current, location)
                        parsed = urlparse(candidate)
                        if parsed.scheme != "https":
                            raise RuntimeError("catalog_redirect_non_https_blocked")
                        current = candidate
                        continue
                    if resp.status_code != 200:
                        raise RuntimeError(f"catalog_http_error:{resp.status_code}")

                    out = bytearray()
                    for chunk in resp.iter_bytes():
                        out.extend(chunk)
                        if len(out) > self.max_bytes:
                            raise RuntimeError("catalog_download_size_limit_exceeded")
                    return bytes(out)
            raise RuntimeError("catalog_redirect_limit_exceeded")

    def _extract_items(self, index_payload: Any) -> list[dict[str, Any]]:
        if isinstance(index_payload, list):
            return [x for x in index_payload if isinstance(x, dict)]
        if isinstance(index_payload, dict):
            if isinstance(index_payload.get("items"), list):
                return [x for x in index_payload["items"] if isinstance(x, dict)]
            if isinstance(index_payload.get("addons"), list):
                out: list[dict[str, Any]] = []
                for raw in index_payload["addons"]:
                    if not isinstance(raw, dict):
                        continue
                    item = {
                        "id": raw.get("id"),
                        "name": raw.get("name") or raw.get("id"),
                        "description": raw.get("description", ""),
                        "categories": raw.get("categories", []),
                        "featured": bool(raw.get("featured", False)),
                        "version": raw.get("version"),
                        "published_at": raw.get("published_at") or raw.get("updated_at") or "",
                    }
                    out.append(item)
                return out
        return []

    def refresh_source(self, source: StoreSource) -> dict[str, Any]:
        if source.type != "github_raw":
            raise RuntimeError("unsupported_source_type")
        source_id = source.id
        source_dir = self._source_dir(source_id)
        source_dir.mkdir(parents=True, exist_ok=True)
        metadata = _safe_json_load(self._metadata_path(source_id))

        fetched: dict[str, bytes] = {}
        try:
            base = source.base_url.rstrip("/")
            for rel in self.REQUIRED_FILES:
                fetched[rel] = self._download_bytes(f"{base}/{rel}")

            _verify_catalog_signatures(
                fetched["catalog/v1/index.json"],
                fetched["catalog/v1/index.json.sig"],
                fetched["catalog/v1/publishers.json"],
                fetched["catalog/v1/publishers.json.sig"],
                self.catalog_public_keys,
            )

            tmp_dir = Path(tempfile.mkdtemp(prefix=f"catalog-{source_id}-", dir=str(self.cache_root)))
            try:
                (tmp_dir / "index.json").write_bytes(fetched["catalog/v1/index.json"])
                (tmp_dir / "index.json.sig").write_bytes(fetched["catalog/v1/index.json.sig"])
                (tmp_dir / "publishers.json").write_bytes(fetched["catalog/v1/publishers.json"])
                (tmp_dir / "publishers.json.sig").write_bytes(fetched["catalog/v1/publishers.json.sig"])

                metadata.update(
                    {
                        "source_id": source_id,
                        "status": "ok",
                        "last_success_at": _utcnow_iso(),
                        "last_error_at": None,
                        "last_error_message": None,
                    }
                )
                (tmp_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

                backup = self.cache_root / f".backup-{source_id}"
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
                if source_dir.exists():
                    os.replace(source_dir, backup)
                os.replace(tmp_dir, source_dir)
                if backup.exists():
                    shutil.rmtree(backup, ignore_errors=True)
            finally:
                if tmp_dir.exists():
                    shutil.rmtree(tmp_dir, ignore_errors=True)
            return {"ok": True, "source_id": source_id, "catalog_status": metadata}
        except Exception as exc:
            err = str(exc) or type(exc).__name__
            metadata.update(
                {
                    "source_id": source_id,
                    "status": "error",
                    "last_error_at": _utcnow_iso(),
                    "last_error_message": err,
                }
            )
            source_dir.mkdir(parents=True, exist_ok=True)
            self._metadata_path(source_id).write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
            return {"ok": False, "source_id": source_id, "catalog_status": metadata}

    def query_cached(self, source_id: str, req: CatalogQuery) -> dict[str, Any]:
        source_dir = self._source_dir(source_id)
        metadata = _safe_json_load(self._metadata_path(source_id))
        index_path = source_dir / "index.json"
        load_error: str | None = None
        payload: Any = []
        if not index_path.exists():
            load_error = "catalog_cache_missing"
        else:
            try:
                payload = json.loads(index_path.read_text(encoding="utf-8"))
            except Exception:
                load_error = "catalog_cache_parse_error"

        items = self._extract_items(payload) if load_error is None else []
        if metadata.get("status") == "error" and not load_error:
            load_error = str(metadata.get("last_error_message") or "catalog_last_refresh_error")

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
            "filters": {"q": req.q, "category": req.category, "featured": req.featured},
            "categories": categories,
            "catalog_status": {
                "status": "error" if load_error else "ok",
                "source_id": source_id,
                "last_success_at": metadata.get("last_success_at"),
                "last_error_at": metadata.get("last_error_at"),
                "last_error_message": load_error,
            },
        }

    def select_source(self, sources: list[StoreSource], source_id: str | None) -> StoreSource | None:
        enabled = [s for s in sources if s.enabled]
        if source_id:
            sid = source_id.strip()
            for src in enabled:
                if src.id == sid:
                    return src
            return None
        for src in enabled:
            if src.id == OFFICIAL_SOURCE_ID:
                return src
        return enabled[0] if enabled else None

    def load_cached_documents(self, source_id: str) -> tuple[Any | None, Any | None]:
        source_dir = self._source_dir(source_id)
        index_path = source_dir / "index.json"
        publishers_path = source_dir / "publishers.json"
        try:
            index_payload = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else None
        except Exception:
            index_payload = None
        try:
            publishers_payload = json.loads(publishers_path.read_text(encoding="utf-8")) if publishers_path.exists() else None
        except Exception:
            publishers_payload = None
        return index_payload, publishers_payload

    def download_artifact(self, url: str) -> bytes:
        return self._download_bytes(url)
