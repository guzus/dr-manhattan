"""Label extraction utilities for chart legends."""


def extract_short_label(label: str) -> str:
    """Extract a short, readable label from a market question."""
    if "?" not in label:
        return label

    q = label.replace("?", "")

    # Fed rate decision patterns
    if "no change" in q.lower():
        return "No change"
    if "decreases" in q.lower() or "decrease" in q.lower():
        if "50+" in q:
            return "Decrease 50+ bps"
        if "25 bps" in q:
            return "Decrease 25 bps"
        if "bps" in q.lower():
            return "Decrease"
    if "increases" in q.lower() or "increase" in q.lower():
        if "25+" in q:
            return "Increase 25+ bps"
        if "bps" in q.lower():
            return "Increase"

    # Nomination patterns
    if "nominate" in q.lower():
        parts = q.split("nominate")[-1].split()
        names = [
            p
            for p in parts
            if p and p[0].isupper() and p.lower() not in ["as", "the", "next", "for"]
        ]
        if names:
            return " ".join(names[:2])

    # Election/win patterns
    if "win" in q.lower() or "elected" in q.lower():
        parts = q.split()
        names = [
            p for p in parts if p and p[0].isupper() and p.lower() not in ["will", "the", "be"]
        ]
        if names:
            return " ".join(names[:2])

    # Fallback: extract capitalized words
    parts = q.split()
    names = [
        p
        for p in parts
        if p
        and len(p) > 1
        and p[0].isupper()
        and p.lower() not in ["will", "the", "be", "in", "on", "by"]
    ]
    if names:
        return " ".join(names[:3])

    return label
