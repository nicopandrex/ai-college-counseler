"""System prompt for audit extraction: the prompt from docs/ plus the input-format addendum."""

from importlib import resources


def extraction_system_prompt() -> str:
    folder = resources.files("planner_ingest.prompts")
    prompt = folder.joinpath("audit_extraction.md").read_text()
    return prompt + "\n" + folder.joinpath("input_format.md").read_text()
