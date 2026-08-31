from __future__ import annotations

import re

from .wiki import DanbooruWiki

NUMERIC_BLOCK = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*::(.*?)::", re.DOTALL)
YEAR_TAG = re.compile(r"year\s+(?:19|20)\d{2}$", re.IGNORECASE)
QUALITY_CONTROLS = {
    "masterpiece", "best quality", "amazing quality", "very aesthetic", "absurdres",
    "highres", "official art", "commission", "artist collaboration", "depth of field",
    "detailed", "highly detailed", "intricate details", "cinematic lighting", "no text",
    "good quality", "normal quality", "low quality", "worst quality",
}
SPECIAL_ARTIST_META = {"artist collaboration", "artist request", "artist name", "artist logo", "artist self-insert", "artist badge"}


def _clean_tag(raw: str) -> tuple[str, float, bool]:
    value = raw.strip().strip(",").strip()
    multiplier = 1.0
    while value.startswith("{"):
        multiplier *= 1.05
        value = value[1:].strip()
    while value.endswith("}"):
        value = value[:-1].strip()
    while value.startswith("["):
        multiplier /= 1.05
        value = value[1:].strip()
    while value.endswith("]"):
        value = value[:-1].strip()

    val_lower = value.lower().replace("_", " ").strip()
    is_explicit_artist = False

    if val_lower in SPECIAL_ARTIST_META:
        return val_lower, multiplier, False

    if (
        val_lower.startswith("artist:") or val_lower.startswith("artist ")
        or val_lower.startswith("artsit:") or val_lower.startswith("artits:")
        or val_lower.startswith("by:") or val_lower.startswith("by ")
    ):
        is_explicit_artist = True
        value = re.sub(r"^(?:artist|artsit|artits|by)\s*[:\s]\s*", "", value, flags=re.IGNORECASE).strip()

    value = value.strip().strip(":").strip()
    return value.replace("_", " "), multiplier, is_explicit_artist


def parse_weighted_prompt(prompt: str) -> list[tuple[str, float, bool]]:
    """Parse NovelAI weight syntax (`n.nn::tag::`, `{tag}`, `[tag]`) into (tag, weight, is_explicit_artist)."""
    positioned: list[tuple[int, str, float, bool]] = []
    spans: list[tuple[int, int]] = []
    for match in NUMERIC_BLOCK.finditer(prompt):
        weight = float(match.group(1))
        spans.append(match.span())
        offset = match.start(2)
        for part in re.finditer(r"[^,]+", match.group(2)):
            raw = part.group(0)
            tag, multiplier, is_artist = _clean_tag(raw)
            if tag:
                positioned.append((offset + part.start(), tag, round(weight * multiplier, 4), is_artist))
    remainder = list(prompt)
    for start, end in spans:
        remainder[start:end] = " " * (end - start)
    for part in re.finditer(r"[^,]+", "".join(remainder)):
        raw = part.group(0)
        tag, multiplier, is_artist = _clean_tag(raw)
        if tag:
            positioned.append((part.start(), tag, round(multiplier, 4), is_artist))

    items = [(tag, weight, is_artist) for _, tag, weight, is_artist in sorted(positioned)]
    deduped: dict[str, tuple[str, float, bool]] = {}
    for tag, weight, is_artist in items:
        key = tag.casefold()
        prev_is_artist = deduped[key][2] if key in deduped else False
        deduped[key] = (tag, weight, is_artist or prev_is_artist)
    return list(deduped.values())


def classify_prompt_genes(prompt: str, wiki: DanbooruWiki | None, configured_quality: list[str]) -> dict:
    """Split a pasted NAI prompt into artist tags (weight + source), quality/control
    tags, and everything else. Artist tags are what feed the fixed BO tag set."""
    artists, qualities, ignored = [], [], []
    quality_names = {tag.casefold().replace("_", " ") for tag in configured_quality} | QUALITY_CONTROLS
    artist_block = False

    for candidate, weight, is_explicit_artist in parse_weighted_prompt(prompt):
        resolved_artist = wiki.resolve_artist(candidate) if wiki else None
        if resolved_artist:
            artists.append({"tag": resolved_artist, "weight": weight, "source": "danbooru-artist"})
            artist_block = True
            continue

        if is_explicit_artist:
            artists.append({"tag": candidate, "weight": weight, "source": "explicit-artist"})
            artist_block = True
            continue

        record = wiki.lookup_exact(candidate) if wiki else None
        normalized = candidate.casefold().strip()
        is_quality = normalized in quality_names or bool(YEAR_TAG.fullmatch(normalized))
        is_quality = is_quality or bool(record and record["category"] == "meta")

        if is_quality:
            artist_block = False
            qualities.append({
                "tag": record["tag"] if record else candidate,
                "weight": weight,
                "source": "danbooru-meta" if record else "novelai-control",
            })
        elif artist_block and not record:
            artists.append({"tag": candidate, "weight": weight, "source": "prompt-artist-block"})
        else:
            if record:
                artist_block = False
            ignored.append({
                "tag": record["tag"] if record else candidate,
                "weight": weight,
                "category": record["category"] if record else "unverified",
            })

    return {"artists": artists, "qualities": qualities, "ignored": ignored}
