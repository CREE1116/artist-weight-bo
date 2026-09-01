from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ArtistTag:
    tag: str
    weight: float


def render_prompt(subject_prompt: str, artist_tags: list[ArtistTag], scene_prompt: str = "", quality_prompt: str = "") -> str:
    """NovelAI weight syntax: plain tag at weight 1.0, else `w.ww:: tag ::`.

    Prompt order (4 sections): subject/count (e.g. `1girl, solo`) → artist
    tags → scene/pose/character description → quality tags.
    """
    parts = []
    for item in artist_tags:
        tag = item.tag if item.tag.startswith("artist:") else f"artist:{item.tag}"
        if abs(item.weight - 1.0) < 0.005:
            parts.append(tag)
        else:
            parts.append(f"{item.weight:.2f}:: {tag} ::")
    artist_section = ", ".join(parts)
    segments = [segment for segment in (subject_prompt, artist_section, scene_prompt, quality_prompt) if segment]
    return ", ".join(segments)
