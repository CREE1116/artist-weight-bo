from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ArtistTag:
    tag: str
    weight: float


def effective_tags(artist_tags: list[ArtistTag], cutoff: float = 0.0, budget_per_tag: float = 0.0) -> list[ArtistTag]:
    """What actually reaches the prompt after cutoff + weight-budget capping.

    `cutoff` treats any tag with weight below it as absent — the tag itself
    stays in the BO search space (still explored/optimized), only this one
    render is missing it, same as if its weight were 0.

    Mixing many artist tags at high weight *simultaneously* is a known way to
    get visually broken NovelAI output, independent of any single tag's
    weight — it's the combined total that overloads attention. `budget_per_tag`
    caps the sum of active weights at `budget_per_tag * (active tag count)`;
    if exceeded, every active weight is scaled down proportionally (ratios
    between tags preserved). This also naturally reins in the very first
    duel, where every tag starts at ~1.0 — with many tags that's already over
    budget, not just something BO drifts into later.

    Callers that display weights to the user should show *this*, not the raw
    input — otherwise what's shown silently diverges from what NovelAI
    actually receives.
    """
    active = [item for item in artist_tags if item.weight >= cutoff]
    if budget_per_tag > 0 and active:
        total = sum(item.weight for item in active)
        budget = budget_per_tag * len(active)
        if total > budget:
            scale = budget / total
            active = [ArtistTag(item.tag, round(item.weight * scale, 2)) for item in active]
    return active


def render_prompt(base_prompt: str, artist_tags: list[ArtistTag], quality_prompt: str = "",
                   cutoff: float = 0.0, budget_per_tag: float = 0.0) -> str:
    """NovelAI weight syntax: plain tag at weight 1.0, else `w.ww::tag::`."""
    active = effective_tags(artist_tags, cutoff, budget_per_tag)
    parts = []
    for item in active:
        tag = item.tag if item.tag.startswith("artist:") else f"artist:{item.tag}"
        if abs(item.weight - 1.0) < 0.005:
            parts.append(tag)
        else:
            parts.append(f"{item.weight:.2f}::{tag}::")
    prefix = ", ".join(parts)
    segments = [segment for segment in (prefix, base_prompt, quality_prompt) if segment]
    return ", ".join(segments)
