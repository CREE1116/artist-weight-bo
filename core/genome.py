from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ArtistTag:
    tag: str
    weight: float


def muted_tags(
    artist_tags: list[ArtistTag],
    weight_cutoff: float = 0.0,
    top_n: int = 0,
) -> set[str]:
    """Tags `render_prompt` would drop for this cutoff/top_n pair — for
    surfacing "muted" state in the UI without re-deriving the drop logic."""
    muted = {item.tag for item in artist_tags if item.weight <= weight_cutoff}
    if top_n > 0:
        survivors = [item for item in artist_tags if item.tag not in muted]
        if len(survivors) > top_n:
            keep_tags = {item.tag for item in sorted(survivors, key=lambda i: i.weight, reverse=True)[:top_n]}
            muted |= {item.tag for item in survivors if item.tag not in keep_tags}
    return muted


def render_prompt(
    subject_prompt: str,
    artist_tags: list[ArtistTag],
    scene_prompt: str = "",
    quality_prompt: str = "",
    weight_cutoff: float = 0.0,
    top_n: int = 0,
) -> str:
    """NovelAI weight syntax: plain tag at weight 1.0, else `w.ww:: tag ::`.

    Prompt order (4 sections): subject/count (e.g. `1girl, solo`) → artist
    tags → scene/pose/character description → quality tags. Artist tags at or
    below `weight_cutoff` are dropped entirely, not just left at weight 1.0.
    If `top_n` > 0, only the `top_n` highest-weight tags surviving the cutoff
    are kept (original relative order preserved).
    """
    muted = muted_tags(artist_tags, weight_cutoff, top_n)
    kept = [item for item in artist_tags if item.tag not in muted]
    parts = []
    for item in kept:
        tag = item.tag if item.tag.startswith("artist:") else f"artist:{item.tag}"
        if abs(item.weight - 1.0) < 0.005:
            parts.append(tag)
        else:
            parts.append(f"{item.weight:.2f}:: {tag} ::")
    artist_section = ", ".join(parts)
    segments = [segment for segment in (subject_prompt, artist_section, scene_prompt, quality_prompt) if segment]
    return ", ".join(segments)
