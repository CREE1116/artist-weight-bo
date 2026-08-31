from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ArtistTag:
    tag: str
    weight: float


def render_prompt(base_prompt: str, artist_tags: list[ArtistTag], quality_prompt: str = "", cutoff: float = 0.0) -> str:
    """NovelAI weight syntax: plain tag at weight 1.0, else `w.ww::tag::`.

    `cutoff` treats any tag with weight below it as absent from the prompt —
    the tag itself stays in the BO search space (still explored/optimized),
    only this one render is missing it, same as if its weight were 0.
    """
    parts = []
    for item in artist_tags:
        if item.weight < cutoff:
            continue
        tag = item.tag if item.tag.startswith("artist:") else f"artist:{item.tag}"
        if abs(item.weight - 1.0) < 0.005:
            parts.append(tag)
        else:
            parts.append(f"{item.weight:.2f}::{tag}::")
    prefix = ", ".join(parts)
    segments = [segment for segment in (prefix, base_prompt, quality_prompt) if segment]
    return ", ".join(segments)
