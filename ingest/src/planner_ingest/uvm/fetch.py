"""Polite one-time fetch from UVM's Schedule of Courses API (CourseLeaf FOSE).

Owner decision (2026-11-18): a one-time pull for Spring 2027 is acceptable, done in well under
50 minutes. The fetcher honours robots.txt, sends an identifying User-Agent, runs a small
fixed pool of workers that each pause between requests, caches every raw response, and never
re-fetches a cached one. serval.uvm.edu (robots: Disallow /) is never contacted.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.robotparser
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

BASE = "https://soc.uvm.edu"
API = f"{BASE}/api/?page=fose&route="
USER_AGENT = "degree-planner-student-project/0.1 (one-time pull for personal planning)"
DELAY_SECONDS = 1.0  # per worker
WORKERS = 6


class Fetcher:
    def __init__(
        self,
        cache_dir: Path,
        client: httpx.Client | None = None,
        delay: float = DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache_dir = cache_dir
        self.client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120)
        self.delay = delay
        self.sleep = sleep
        self.requests = 0
        self._lock = threading.Lock()

    def check_robots(self) -> None:
        response = self.client.get(f"{BASE}/robots.txt")
        if response.status_code == 404:
            return
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        if not parser.can_fetch(USER_AGENT, API):
            raise PermissionError("soc.uvm.edu robots.txt disallows the API; not fetching")

    def _post(self, route: str, body: dict[str, Any], cache_name: str) -> dict[str, Any]:
        path = self.cache_dir / cache_name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        with self._lock:
            pause = self.requests > 0
            self.requests += 1
        if pause:
            self.sleep(self.delay)
        response = self.client.post(API + route, json=body)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text, encoding="utf-8")
        return response.json()

    def search(self, srcdb: str) -> dict[str, Any]:
        return self._post("search", {"other": {"srcdb": srcdb}, "criteria": []}, "search_all.json")

    def details(self, srcdb: str, code: str, crn: str) -> dict[str, Any]:
        body = {
            "group": f"code:{code}",
            "key": f"crn:{crn}",
            "srcdb": srcdb,
            "matched": f"crn:{crn}",
        }
        return self._post("details", body, f"details/{code.replace(' ', '_')}.json")


def pull_term(
    srcdb: str,
    cache_root: Path,
    fetcher: Fetcher | None = None,
    log: Callable[[str], None] = print,
    workers: int = WORKERS,
) -> Path:
    """Search once, then one details call per course (cached). Returns the cache directory."""
    cache_dir = cache_root / srcdb
    fetcher = fetcher or Fetcher(cache_dir)
    fetcher.check_robots()
    results = fetcher.search(srcdb)["results"]
    first_section: dict[str, str] = {}
    for row in results:
        first_section.setdefault(row["code"], row["crn"])
    done = 0

    def one(item: tuple[str, str]) -> None:
        nonlocal done
        fetcher.details(srcdb, *item)
        with fetcher._lock:
            done += 1
            if done % 100 == 0:
                log(f"{done}/{len(first_section)} courses ({fetcher.requests} requests made)")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, sorted(first_section.items())))
    log(f"done: {len(results)} sections, {len(first_section)} courses, {fetcher.requests} requests")
    return cache_dir
