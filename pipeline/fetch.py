"""Download every enabled source listed in sources.csv.

sources.csv columns:
  id            unique name; files are saved under data/raw/<id>/
  enabled       1 = fetch, 0 = skip
  kind          file  -> download `url` as-is
                index -> download the HTML at `url`, find links matching
                         `link_pattern` (regex) and download those
  parser        which extractor reads the file (see pipeline/build.py), or none
  url           base link
  link_pattern  (index only) regex for the links; group 1 is used to sort
  select        (index only) all | latest
  description   free text
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
import truststore

from . import config

truststore.inject_into_ssl()  # use the OS certificate store (needed on some Windows setups)

CONTENT_EXT = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "text/csv": ".csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
}


@dataclass
class Source:
    id: str
    enabled: bool
    kind: str
    parser: str
    url: str
    link_pattern: str
    select: str
    description: str


@dataclass
class Downloaded:
    source_id: str
    parser: str
    url: str
    path: Path
    sha256: str
    bytes: int
    downloaded_at: str
    cached: bool


def load_sources(path: Path = config.SOURCES_CSV) -> list[Source]:
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    sources = []
    for r in rows:
        sources.append(
            Source(
                id=r["id"].strip(),
                enabled=r.get("enabled", "1").strip() in {"1", "true", "True", "yes"},
                kind=(r.get("kind") or "file").strip(),
                parser=(r.get("parser") or "none").strip() or "none",
                url=r["url"].strip(),
                link_pattern=(r.get("link_pattern") or "").strip(),
                select=(r.get("select") or "all").strip() or "all",
                description=(r.get("description") or "").strip(),
            )
        )
    ids = [s.id for s in sources]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"Duplicate ids in sources.csv: {sorted(dupes)}")
    return sources


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = config.USER_AGENT
    return s


def _ext_for(resp: requests.Response, url: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename="?([^";]+)"?', cd)
    if m:
        return Path(m.group(1)).suffix.lower()
    ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if ctype in CONTENT_EXT:
        return CONTENT_EXT[ctype]
    return Path(url.split("?")[0]).suffix.lower() or ".bin"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(session, src: Source, url: str, stem: str, force: bool) -> Downloaded:
    folder = config.RAW_DIR / src.id
    folder.mkdir(parents=True, exist_ok=True)
    existing = sorted(folder.glob(f"{stem}.*"))
    if existing and not force:
        path = existing[0]
        return Downloaded(src.id, src.parser, url, path, _sha256(path), path.stat().st_size,
                          "", cached=True)
    resp = session.get(url, timeout=120)
    resp.raise_for_status()
    path = folder / f"{stem}{_ext_for(resp, url)}"
    for old in existing:
        old.unlink()
    path.write_bytes(resp.content)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return Downloaded(src.id, src.parser, url, path, _sha256(path), len(resp.content), now,
                      cached=False)


def _index_links(session, src: Source) -> list[tuple[str, str]]:
    """Return [(absolute_url, stem)] for links on the index page matching link_pattern."""
    if not src.link_pattern:
        raise ValueError(f"{src.id}: kind=index needs link_pattern")
    html = session.get(src.url, timeout=60)
    html.raise_for_status()
    hrefs = re.findall(r"""href\s*=\s*["']?([^"' >]+)""", html.text, flags=re.I)
    rx = re.compile(src.link_pattern)
    found: dict[str, tuple[str, str]] = {}
    for href in hrefs:
        m = rx.search(href)
        if m:
            key = m.group(1) if m.groups() else m.group(0)
            found[key] = (urljoin(src.url, href), Path(href.split("?")[0]).stem)
    if not found:
        raise RuntimeError(f"{src.id}: no links matched {src.link_pattern!r} on {src.url}")
    keys = sorted(found)
    if src.select == "latest":
        keys = keys[-1:]
    return [found[k] for k in keys]


def fetch_all(force: bool = False, only: list[str] | None = None) -> list[Downloaded]:
    """Download all enabled sources (skips files already on disk unless force=True)."""
    session = _session()
    results: list[Downloaded] = []
    for src in load_sources():
        if not src.enabled or (only and src.id not in only):
            continue
        try:
            if src.kind == "file":
                targets = [(src.url, src.id)]
            elif src.kind == "index":
                targets = _index_links(session, src)
            else:
                raise ValueError(f"unknown kind {src.kind!r}")
            for url, stem in targets:
                d = _download(session, src, url, stem, force)
                results.append(d)
                print(f"[{'cache' if d.cached else 'get  '}] {src.id}: {d.path.name}")
        except Exception as e:  # keep going; report at the end
            print(f"[FAIL ] {src.id}: {e}")
    _write_manifest(results)
    return results


def _write_manifest(results: list[Downloaded]) -> None:
    """data/manifest.csv: one row per local file (url, date, sha256), merged with previous runs."""
    rows: dict[str, dict] = {}
    if config.MANIFEST_CSV.exists():
        with open(config.MANIFEST_CSV, encoding="utf-8", newline="") as f:
            rows = {r["local_path"]: r for r in csv.DictReader(f)}
    for d in results:
        rel = d.path.relative_to(config.ROOT).as_posix()
        prev = rows.get(rel, {})
        rows[rel] = {
            "source_id": d.source_id,
            "url": d.url,
            "local_path": rel,
            "downloaded_at": d.downloaded_at or prev.get("downloaded_at", ""),
            "sha256": d.sha256,
            "bytes": d.bytes,
        }
    config.MANIFEST_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = ["source_id", "url", "local_path", "downloaded_at", "sha256", "bytes"]
    with open(config.MANIFEST_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])
