import json
from pathlib import Path

import httpx
import pytest

from planner_ingest.uvm.fetch import Fetcher, pull_term

SEARCH = {
    "srcdb": "202701",
    "count": 3,
    "results": [
        {"code": "CS 1210", "crn": "1"},
        {"code": "CS 1210", "crn": "2"},
        {"code": "MATH 1234", "crn": "3"},
    ],
}


def transport(calls: list[str], robots: str | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path} {request.url.query.decode()}")
        if request.url.path == "/robots.txt":
            return httpx.Response(404) if robots is None else httpx.Response(200, text=robots)
        if "route=search" in str(request.url):
            return httpx.Response(200, json=SEARCH)
        body = json.loads(request.content)
        return httpx.Response(200, json={"code": body["group"][5:], "hours_html": "3"})

    return httpx.MockTransport(handler)


def make(
    tmp_path: Path, calls: list[str], robots: str | None = None, sleeps: list[float] | None = None
):
    client = httpx.Client(transport=transport(calls, robots), base_url="https://soc.uvm.edu")
    return Fetcher(
        tmp_path / "202701", client=client, sleep=(sleeps if sleeps is not None else []).append
    )


def test_one_search_and_one_details_call_per_course(tmp_path: Path) -> None:
    calls: list[str] = []
    sleeps: list[float] = []
    pull_term("202701", tmp_path, make(tmp_path, calls, sleeps=sleeps), log=lambda _: None)
    posts = [c for c in calls if c.startswith("POST")]
    assert len(posts) == 3  # search + CS 1210 + MATH 1234
    assert len(sleeps) == 2  # a pause before every request after the first


def test_cached_responses_are_never_refetched(tmp_path: Path) -> None:
    first: list[str] = []
    pull_term("202701", tmp_path, make(tmp_path, first), log=lambda _: None)
    second: list[str] = []
    pull_term("202701", tmp_path, make(tmp_path, second), log=lambda _: None)
    assert [c for c in second if c.startswith("POST")] == []


def test_robots_disallow_stops_everything(tmp_path: Path) -> None:
    calls: list[str] = []
    with pytest.raises(PermissionError):
        pull_term(
            "202701",
            tmp_path,
            make(tmp_path, calls, robots="User-agent: *\nDisallow: /"),
            log=lambda _: None,
        )
    assert [c for c in calls if c.startswith("POST")] == []
