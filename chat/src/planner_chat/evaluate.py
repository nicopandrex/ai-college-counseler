"""Translator eval: 50 utterances with expected specs, scored automatically.

An utterance passes when the mode matches; every expected constraint (or one listed
alternative set) is matched one-to-one on type, params, enforcement and weight (±1); nothing
unexpected is added (the system's default credit range and listed `allow_extra` types aside);
and out-of-scope requests land in `out_of_scope`.

  uv run python -m planner_chat.evaluate        # replay (LLM_CACHE_MODE=record to call the model)
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from planner_chat.translator import TranslatorContext, translate
from planner_llm import CacheMode, LLMError, LLMGateway
from planner_llm.gateway import provider_from_env

EVAL_DIR = Path("evals/translator")
PASS_BAR = 0.9


@dataclass
class Result:
    id: str
    passed: bool
    category: str | None = None
    detail: str = ""


def _norm(value: Any, key: str) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, list):
        return frozenset(_norm(v, key) for v in value)
    text = str(value).strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        hours, minutes = text.split(":")
        return f"{int(hours):02d}:{minutes}"
    if key == "name":  # instructor: compare last names ("Smith, John" / "Professor John Smith")
        return (text.split(",")[0] if "," in text else text.split()[-1]).casefold()
    return text.casefold()


def _params_match(expected: dict[str, Any], produced: dict[str, Any]) -> bool:
    for key, want in expected.items():
        got = produced.get(key)
        if isinstance(want, dict) and "one_of" in want:
            if _norm(got, key) not in {_norm(v, key) for v in want["one_of"]}:
                return False
        elif _norm(got, key) != _norm(want, key):
            return False
    return True


def _check(want: dict[str, Any], got: dict[str, Any]) -> str | None:
    """None if `got` satisfies `want`, else the failing aspect."""
    if got["type"] != want["type"]:
        return "missing"
    if not _params_match(want["params"], got["params"]):
        return "params"
    enforcements = (
        want["enforcement"] if isinstance(want["enforcement"], list) else [want["enforcement"]]
    )
    if got["enforcement"] not in enforcements:
        return "enforcement"
    if want.get("weight") is not None and abs(got["weight"] - want["weight"]) > 1:
        return "weight"
    return None


def _match(expected: list[dict[str, Any]], produced: list[dict[str, Any]]) -> list[int] | None:
    """Indexes of produced constraints matched one-to-one to `expected`, or None."""

    def search(i: int, used: frozenset[int]) -> list[int] | None:
        if i == len(expected):
            return []
        for j, got in enumerate(produced):
            if j not in used and _check(expected[i], got) is None:
                rest = search(i + 1, used | {j})
                if rest is not None:
                    return [j, *rest]
        return None

    return search(0, frozenset())


def _diagnose(expected: list[dict[str, Any]], produced: list[dict[str, Any]]) -> tuple[str, str]:
    order = ["params", "enforcement", "weight"]
    for want in expected:
        same_type = [got for got in produced if got["type"] == want["type"]]
        if not same_type:
            return f"missing:{want['type']}", json.dumps(want["params"])
        if all(_check(want, got) is not None for got in same_type):
            worst = min((_check(want, got) for got in same_type), key=order.index)
            shown = [{k: g[k] for k in ("params", "enforcement", "weight")} for g in same_type]
            return f"{worst}:{want['type']}", f"want {json.dumps(want)} got {json.dumps(shown)}"
    return "unknown", ""


def score(item: dict[str, Any], spec: dict[str, Any]) -> Result:
    if spec.get("mode") != item.get("mode", "term"):
        return Result(item["id"], False, "mode", f"got {spec.get('mode')}")
    expected_types = {e["type"] for e in item["expected"]}
    produced = [
        c
        for c in spec.get("constraints", [])
        if not (
            c["type"] == "credit_range"
            and c.get("weight_source") == "default"
            and "credit_range" not in expected_types
        )
    ]
    if item.get("expect_out_of_scope") and not spec.get("out_of_scope"):
        return Result(item["id"], False, "out_of_scope_missing")
    allowed_extra = set(item.get("allow_extra", []))
    for candidate in [item["expected"], *item.get("alternatives", [])]:
        matched = _match(candidate, produced)
        if matched is None:
            continue
        extras = [
            c for j, c in enumerate(produced) if j not in matched and c["type"] not in allowed_extra
        ]
        if not extras:
            return Result(item["id"], True)
    matched = _match(item["expected"], produced)
    if matched is not None:
        extras = [
            c for j, c in enumerate(produced) if j not in matched and c["type"] not in allowed_extra
        ]
        return Result(
            item["id"], False, f"extra:{extras[0]['type']}", json.dumps(extras[0]["params"])
        )
    category, detail = _diagnose(item["expected"], produced)
    return Result(item["id"], False, category, detail)


def load(eval_dir: Path = EVAL_DIR) -> tuple[TranslatorContext, list[dict[str, Any]]]:
    raw = json.loads((eval_dir / "context.json").read_text())
    context = TranslatorContext(
        target_term=raw["target_term"],
        open_requirements=[tuple(r) for r in raw["open_requirements"]],  # type: ignore[misc]
        catalog=[tuple(c) for c in raw["catalog"]],  # type: ignore[misc]
        programs=[tuple(p) for p in raw["programs"]],  # type: ignore[misc]
    )
    items = [
        json.loads(line)
        for line in (eval_dir / "utterances.jsonl").read_text().splitlines()
        if line
    ]
    return context, items


def run(
    gateway: LLMGateway, eval_dir: Path = EVAL_DIR, workers: int = 6
) -> list[tuple[dict[str, Any], Result, dict[str, Any] | None]]:
    context, items = load(eval_dir)

    def one(item: dict[str, Any]) -> tuple[dict[str, Any], Result, dict[str, Any] | None]:
        try:
            translation = translate(item["message"], context, gateway, prior=item.get("prior"))
        except LLMError as exc:
            return item, Result(item["id"], False, "llm_error", str(exc)[:200]), None
        if translation.problems:
            return (
                item,
                Result(item["id"], False, "bad_params_json", "; ".join(translation.problems)),
                translation.spec,
            )
        return item, score(item, translation.spec), translation.spec

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, items))


def main() -> int:
    parser = argparse.ArgumentParser(prog="planner_chat.evaluate")
    parser.add_argument(
        "--model", default=os.environ.get("LLM_MODEL_TRANSLATE", "gemini-3.5-flash")
    )
    parser.add_argument("--out", type=Path, default=EVAL_DIR / "report.json")
    args = parser.parse_args()
    mode = CacheMode(os.environ.get("LLM_CACHE_MODE", "replay"))
    gateway = LLMGateway(provider_from_env(), args.model, EVAL_DIR / "cassettes", mode)
    outcomes = run(gateway)
    passed = sum(r.passed for _, r, _ in outcomes)
    categories = Counter((r.category or "").split(":")[0] for _, r, _ in outcomes if not r.passed)
    rate = passed / len(outcomes)
    print(f"{args.model}: {passed}/{len(outcomes)} passed ({rate:.0%}); bar {PASS_BAR:.0%}")
    for category, count in categories.most_common():
        print(f"  {category}: {count}")
    for item, result, _ in outcomes:
        if not result.passed:
            message = item["message"][:70]
            print(f"  ✗ {result.id} [{result.category}] {message!r} {result.detail[:220]}")
    report = {
        "model": args.model,
        "passed": passed,
        "total": len(outcomes),
        "results": [{**asdict(r), "message": i["message"], "spec": s} for i, r, s in outcomes],
    }
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
