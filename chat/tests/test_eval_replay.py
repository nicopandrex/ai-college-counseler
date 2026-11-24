"""M6 done-bar, replayed from the recorded cassettes (no network, no cost)."""

from pathlib import Path

import pytest

from planner_chat.evaluate import PASS_BAR, run
from planner_llm import CacheMode, LLMGateway
from planner_llm.providers.gemini import GeminiProvider

EVAL_DIR = Path(__file__).resolve().parents[2] / "evals" / "translator"
MODEL = "gemini-3.5-flash"


@pytest.mark.skipif(not (EVAL_DIR / "cassettes").exists(), reason="no recorded eval run")
def test_translator_eval_meets_the_bar() -> None:
    gateway = LLMGateway(
        GeminiProvider(api_key="replay-only"), MODEL, EVAL_DIR / "cassettes", CacheMode.REPLAY
    )
    outcomes = run(gateway, EVAL_DIR)
    passed = sum(result.passed for _, result, _ in outcomes)
    assert len(outcomes) == 50
    assert passed / len(outcomes) >= PASS_BAR
