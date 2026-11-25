"""Natural wording for a reply whose facts the system already worked out.

The LLM rewrites a templated draft. The rewrite is shown only if it passes `ungrounded`: the
same course codes as the draft, and no time, number, number word or instructor name the draft
doesn't contain. Anything else (or any LLM error) shows the draft itself, so a fact is never
invented, changed or dropped by the wording step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources

from planner_llm import JsonRequest, LLMError, LLMGateway

PURPOSE = "phrase"
_CODE = re.compile(r"\b[A-Z]{2,5} \d{4}[A-Z]?\b")
_TIME = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)")  # "4:45" in "4:45pm" too
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_WORDS = {
    w: str(n)
    for n, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
}
_WORD = re.compile(r"\b(" + "|".join(_WORDS) + r")\b", re.IGNORECASE)
_UNITS = {
    "credit": "credit",
    "credits": "credit",
    "cr": "credit",
    "course": "course",
    "courses": "course",
    "class": "course",
    "classes": "course",
    "section": "section",
    "sections": "section",
    "requirement": "requirement",
    "requirements": "requirement",
    "schedule": "plan",
    "schedules": "plan",
    "plan": "plan",
    "plans": "plan",
}
# "3 credits", "5 ECON courses", "two more sections": an amount and what it counts
_AMOUNT = re.compile(
    r"\b(\d+(?:\.\d+)?|"
    + "|".join(_WORDS)
    + r")[\s-]+(?:(?!(?:"
    + "|".join(_UNITS)
    + r")\b)[A-Za-z]+\s+)?("  # one word may sit between ("5 ECON courses"), not a unit
    + "|".join(_UNITS)
    + r")\b",
    re.IGNORECASE,
)
SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}},
    "required": ["reply"],
    "additionalProperties": False,
}


def _numbers(text: str) -> set[str]:
    """Standalone numbers (not inside course codes or times), number words as digits."""
    rest = _TIME.sub(" ", _CODE.sub(" ", text))
    found = {n.rstrip("0").rstrip(".") if "." in n else n for n in _NUMBER.findall(rest)}
    return found | {_WORDS[w.lower()] for w in _WORD.findall(rest)}


def _amounts(text: str) -> tuple[set[tuple[str, str]], set[str]]:
    """Each number with the unit it counts (("3", "credit"), ("5", "course")), and the
    numbers stated without a unit ("you can take 4", "and 1 more")."""
    rest = _TIME.sub(" ", _CODE.sub(" ", text))
    found = set()
    for number, unit in _AMOUNT.findall(rest):
        value = _WORDS.get(number.lower(), number)
        value = value.rstrip("0").rstrip(".") if "." in value else value
        found.add((value, _UNITS[unit.lower()]))
    return found, _numbers(_AMOUNT.sub(" ", rest))


def ungrounded(draft: str, reply: str, names: frozenset[str] = frozenset()) -> list[str]:
    """Why `reply` can't stand in for `draft` (empty: it can)."""
    problems: list[str] = []
    codes, said = set(_CODE.findall(draft)), set(_CODE.findall(reply))
    if added := said - codes:
        problems.append(f"courses not in the draft: {sorted(added)}")
    if dropped := codes - said:
        problems.append(f"courses left out: {sorted(dropped)}")
    if times := set(_TIME.findall(reply)) - set(_TIME.findall(draft)):
        problems.append(f"times not in the draft: {sorted(times)}")
    if numbers := _numbers(reply) - _numbers(draft):
        problems.append(f"numbers not in the draft: {sorted(numbers)}")
    stated, bare = _amounts(draft)
    said_amounts, _ = _amounts(reply)
    # a unit may be added to a bare number ("take 4" -> "4 courses"), never changed
    if amounts := {(n, u) for n, u in said_amounts - stated if n not in bare}:
        problems.append(f"amounts not in the draft: {sorted(amounts)}")
    # every credit and course amount the draft states stays in the reply
    if lost := {(n, u) for n, u in stated - said_amounts if u in ("credit", "course")}:
        problems.append(f"amounts left out: {sorted(lost)}")
    for name in sorted(names):
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        if pattern.search(reply) and not pattern.search(draft):
            problems.append(f"instructor not in the draft: {name}")
    return problems


@dataclass
class Phraser:
    gateway: LLMGateway
    names: frozenset[str] = frozenset()  # instructor surnames in the term data
    fallbacks: int = 0  # rewrites rejected (or failed) this conversation
    last_problems: list[str] = field(default_factory=list)  # why the last one was rejected

    def reword(self, draft: str, message: str) -> str:
        if not draft.strip():
            return draft
        folder = resources.files("planner_chat.prompts")
        request = JsonRequest(
            purpose=PURPOSE,
            system=folder.joinpath("phrasing.md").read_text(encoding="utf-8"),
            user=f"MESSAGE:\n{message}\n\nDRAFT:\n{draft}\n",
            schema=SCHEMA,
            max_tokens=4000,
            effort="low",
        )
        try:
            reply = str(self.gateway.complete_json(request).get("reply", "")).strip()
        except LLMError:
            reply = ""
        self.last_problems = ungrounded(draft, reply, self.names) if reply else ["no reply"]
        if self.last_problems:
            self.fallbacks += 1
            return draft
        return reply


def instructor_names(instructors: list[str]) -> frozenset[str]:
    """Surnames from "S. Smith" / "Smith, John A" / "Ana Diaz" (3+ letters, capitalized)."""
    names: set[str] = set()
    for full in instructors:
        last = full.split(",")[0] if "," in full else full.split()[-1] if full.split() else ""
        last = last.strip(" .")
        if len(last) >= 3 and last[0].isupper() and last.replace("-", "").isalpha():
            names.add(last)
    return frozenset(names)
