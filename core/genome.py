from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ArtistTag:
    tag: str
    weight: float


def render_prompt(base_prompt: str, artist_tags: list[ArtistTag], quality_prompt: str = "") -> str:
    """NovelAI weight syntax: plain tag at weight 1.0, else `w.ww::tag::`."""
    parts = []
    for item in artist_tags:
        if abs(item.weight - 1.0) < 0.005:
            parts.append(item.tag)
        else:
            parts.append(f"{item.weight:.2f}::{item.tag}::")
    prefix = ", ".join(parts)
    segments = [segment for segment in (prefix, base_prompt, quality_prompt) if segment]
    return ", ".join(segments)
