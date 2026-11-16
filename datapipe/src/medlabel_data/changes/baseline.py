"""Baseline method for T5: a text-similarity rule.

A candidate is labeled "meaning changed" when its similarity is below THETA, else "reworded".
Similarity is the token similarity from align.py: between the old and new sentence for an
altered pair, and with the closest sentence on the other side for an added or removed
sentence. THETA was chosen on the development sample only (docs/label-changes.md), never on T5.
Whole-section events are not candidates for this rule; they are always shown as changes.
"""

MEANING = "meaning changed"
REWORDED = "reworded"
LABELS = (MEANING, REWORDED)

THETA = 0.75


def baseline_label(similarity: float, theta: float = THETA) -> str:
    return MEANING if similarity < theta else REWORDED
