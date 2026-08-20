"""
Grounding checks for reasoning/narrative.py's output.

The narrative prompt (build_narrative_prompt) instructs the model not
to invent, recompute, or restate any pace/time/fueling/grade number
that isn't already in the structured plan it's given. That instruction
is not an enforcement mechanism -- an LLM can ignore it. This module is
the check: does the narrative's prose actually stay grounded in the
structured plan, or does it state a number that doesn't appear there?

Approach: no LLM judge, just regex extraction + exact/range matching
against the structured plan (per the eval harness spec's "automatable,
no LLM judge needed" grounding-check design). This is deliberately
narrow and will miss paraphrased or prose-only claims ("that climb is
brutal" isn't checkable) -- it only catches numeric claims with a
recognizable pattern (paces, total times, fueling rates, grade
percentages). It will also produce occasional false positives: any
number that happens to match one of these patterns for an unrelated
reason (e.g. "50%" used as a vague qualifier, not a grade) gets flagged
even though it's not really a grounding violation. That's an accepted
tradeoff of pattern-matching over an LLM judge -- cheap, deterministic,
and zero additional API cost, at the price of precision.

Nothing in this module calls an LLM or costs money.
"""

import re
from dataclasses import dataclass
from typing import List


PACE_PATTERN = re.compile(r"\b(\d{1,2}:[0-5]\d)/km\b")
TOTAL_TIME_PATTERN = re.compile(r"\b(\d{1,2}:[0-5]\d:[0-5]\d)\b")
FUELING_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?)\s*(g/hr|ml/hr|mg/hr)\b")
GRADE_PATTERN = re.compile(r"\b([+-]?\d+(?:\.\d+)?)%")


@dataclass
class GroundingViolation:
    kind: str  # "pace" | "total_time" | "fueling" | "grade"
    mentioned: str
    reason: str


@dataclass
class GroundingReport:
    violations: List[GroundingViolation]
    checked_pace_mentions: List[str]
    checked_time_mentions: List[str]

    @property
    def is_grounded(self) -> bool:
        return len(self.violations) == 0


def _format_hms(total_seconds: float) -> str:
    """Matches race_plan.py's H:MM:SS formatting exactly, so the comparison is apples-to-apples."""
    total_seconds = int(total_seconds)
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h}:{m:02d}:{s:02d}"


def check_narrative_grounding(narrative_text: str, structured_plan: dict) -> GroundingReport:
    violations = []

    # --- pace mentions ---
    # target_pace is e.g. "6:04/km"; the regex capture group excludes
    # the "/km" suffix, so strip it here for an apples-to-apples compare.
    valid_paces = {seg["target_pace"].replace("/km", "") for seg in structured_plan["course"]["segments"]}
    mentioned_paces = PACE_PATTERN.findall(narrative_text)
    for pace in mentioned_paces:
        if pace not in valid_paces:
            violations.append(GroundingViolation(
                kind="pace",
                mentioned=f"{pace}/km",
                reason="not the target pace of any segment in the structured plan",
            ))

    # --- total time mentions ---
    predicted_time_str = _format_hms(structured_plan["course"]["predicted_time_sec"])
    mentioned_times = TOTAL_TIME_PATTERN.findall(narrative_text)
    for t in mentioned_times:
        if t != predicted_time_str:
            violations.append(GroundingViolation(
                kind="total_time",
                mentioned=t,
                reason=f"doesn't match the plan's predicted time ({predicted_time_str})",
            ))

    # --- fueling mentions (allowed to fall anywhere inside the range, not just the exact bound) ---
    fueling = structured_plan["fueling"]
    fueling_bounds = {
        "g/hr": (fueling["carbs_g_per_hr"], fueling["carbs_g_per_hr"]),
        "ml/hr": (fueling["fluid_ml_per_hr_low"], fueling["fluid_ml_per_hr_high"]),
        "mg/hr": (fueling["sodium_mg_per_hr_low"], fueling["sodium_mg_per_hr_high"]),
    }
    for value_str, unit in FUELING_PATTERN.findall(narrative_text):
        value = float(value_str)
        low, high = fueling_bounds[unit]
        tolerance = 0.5  # rounding slack, since the narrative may round to whole units
        if not (low - tolerance <= value <= high + tolerance):
            violations.append(GroundingViolation(
                kind="fueling",
                mentioned=f"{value_str} {unit}",
                reason=f"outside the plan's {unit} range ({low:.0f}-{high:.0f})",
            ))

    # --- grade percentage mentions ---
    valid_grades = {round(seg["grade_pct"], 1) for seg in structured_plan["course"]["segments"]}
    for value_str in GRADE_PATTERN.findall(narrative_text):
        value = round(float(value_str), 1)
        if value not in valid_grades:
            violations.append(GroundingViolation(
                kind="grade",
                mentioned=f"{value_str}%",
                reason="doesn't match any segment's grade in the structured plan",
            ))

    return GroundingReport(
        violations=violations,
        checked_pace_mentions=mentioned_paces,
        checked_time_mentions=mentioned_times,
    )


def evaluate_race_narrative(result) -> GroundingReport:
    """Convenience wrapper: check a reasoning.narrative.RaceNarrative's own output against itself."""
    return check_narrative_grounding(result.narrative_text, result.structured_plan)
