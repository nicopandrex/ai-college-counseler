import os
from pathlib import Path

import pytest

from planner_llm.envfile import load_env_file


def test_env_file_fills_unset_variables_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        '# comment\nPLANNER_T_A="from file"\nPLANNER_T_B=file\n\nnot a line\n', encoding="utf-8"
    )
    monkeypatch.delenv("PLANNER_T_A", raising=False)
    monkeypatch.setenv("PLANNER_T_B", "real")
    load_env_file(env)
    assert os.environ["PLANNER_T_A"] == "from file" and os.environ["PLANNER_T_B"] == "real"


def test_a_missing_env_file_is_fine(tmp_path: Path) -> None:
    load_env_file(tmp_path / "nope")
