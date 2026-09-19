"""Part identification from a single-brick crop.

Default backend is the free Brickognize API (Vidal et al., Sensors 23(4):1898, 2023).

⚠️ Every /predict/* endpoint in its live OpenAPI spec is marked `deprecated: true` -- only
/health/ is not. It is a free hobby service and we will hit it ~60 times live on stage. So:
  * EVERY response is cached to disk, keyed by the SHA-256 of the crop bytes. The demo runs from
    cache, the network is a cold-start detail.
  * Failures degrade to `unknown` and never raise. One bad crop must not kill a batch.
  * A concurrency cap and a short timeout keep us polite.

It also returns exactly ONE bounding_box per image -- it is single-object recognition, not pile
parsing. We still need our own segmenter; that is `vision/segment.py`.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import pathlib
import time
from dataclasses import dataclass, asdict

import requests

API = os.environ.get("BRICKOGNIZE_URL", "https://api.brickognize.com/predict/parts/")
CACHE_DIR = pathlib.Path(os.environ.get(
    "BRICKOGNIZE_CACHE",
    pathlib.Path(__file__).resolve().parents[1] / "data" / "brickognize_cache"))
TIMEOUT = float(os.environ.get("BRICKOGNIZE_TIMEOUT", "8"))
MAX_WORKERS = int(os.environ.get("BRICKOGNIZE_WORKERS", "6"))


@dataclass
class Candidate:
    part: str
    name: str
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


def _cache_path(digest: str) -> pathlib.Path:
    return CACHE_DIR / digest[:2] / f"{digest}.json"


def _read_cache(digest: str) -> list[dict] | None:
    p = _cache_path(digest)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _write_cache(digest: str, items: list[dict]) -> None:
    p = _cache_path(digest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items))


def classify_bytes(png: bytes, *, top_k: int = 5, use_cache: bool = True) -> list[Candidate]:
    """Identify one cropped brick. Never raises -- an empty list means 'unknown'."""
    digest = hashlib.sha256(png).hexdigest()
    if use_cache:
        cached = _read_cache(digest)
        if cached is not None:
            return [Candidate(**c) for c in cached][:top_k]

    items: list[dict] = []
    try:
        r = requests.post(
            API,
            files={"query_image": ("crop.png", png, "image/png")},
            timeout=TIMEOUT,
            headers={"User-Agent": "Bricolage/0.1 (hackathon project)"},
        )
        if r.status_code == 200:
            for it in (r.json() or {}).get("items", []) or []:
                pid = str(it.get("id", "")).strip()
                if not pid:
                    continue
                items.append({"part": pid, "name": it.get("name", pid),
                              "score": float(it.get("score", 0.0))})
    except (requests.RequestException, ValueError, KeyError):
        items = []

    if items:
        _write_cache(digest, items)
    return [Candidate(**c) for c in items][:top_k]


def classify_many(crops: list[bytes], *, top_k: int = 5,
                  progress=None) -> list[list[Candidate]]:
    """Classify a batch concurrently, politely, in input order."""
    results: list[list[Candidate]] = [[] for _ in crops]
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(classify_bytes, c, top_k=top_k): i for i, c in enumerate(crops)}
        for fut in concurrent.futures.as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception:
                results[i] = []
            done += 1
            if progress:
                progress(done, len(crops))
    return results


def health() -> bool:
    try:
        r = requests.get("https://api.brickognize.com/health/", timeout=TIMEOUT)
        return r.status_code == 200
    except requests.RequestException:
        return False


def cache_stats() -> dict:
    if not CACHE_DIR.exists():
        return {"entries": 0, "bytes": 0}
    files = list(CACHE_DIR.rglob("*.json"))
    return {"entries": len(files), "bytes": sum(f.stat().st_size for f in files)}
