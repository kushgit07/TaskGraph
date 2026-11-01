"""Faithfulness checker — a SEPARATE pass from the terminal agent that
wrote the report. Extracts numeric claims from the report text and
verifies each against the actual computed artifact values before the
report is shown to the user.

Known limitation (documented, not hidden — see DESIGN.md section 5): this
is a numeric-claim heuristic, not a full natural-language entailment
model. It catches fabricated numbers; it does not catch fabricated
qualitative claims ("trending upward" when it isn't). A stronger version
would add a second LLM call to verify each sentence's claim against the
artifact data directly.
"""
import re

_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*%?")


def _extract_numbers(text: str) -> list[str]:
    return _NUMBER_RE.findall(text)


def _normalize(num_str: str) -> str:
    return num_str.replace(",", "").rstrip("%")


def check_faithfulness(report_text: str, artifact_previews: dict) -> dict:
    """Returns {"unsupported_claims": [...], "checked_claims": n}."""
    report_numbers = {_normalize(n) for n in _extract_numbers(report_text)}
    artifact_text = " ".join(str(v) for v in artifact_previews.values())
    artifact_numbers = {_normalize(n) for n in _extract_numbers(artifact_text)}

    unsupported = []
    for num in report_numbers:
        if not num:
            continue
        if num in artifact_numbers:
            continue
        # tolerance: allow rounding to 1 decimal place
        try:
            val = float(num)
            if any(abs(val - float(a)) < 0.1 for a in artifact_numbers if a):
                continue
        except ValueError:
            pass
        unsupported.append(num)

    return {
        "unsupported_claims": unsupported,
        "checked_claims": len(report_numbers),
    }
