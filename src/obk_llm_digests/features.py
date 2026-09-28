from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Feature:
    """A business feature and the terms used to locate its implementation."""

    id: str
    title: str
    keywords: tuple[str, ...]


def load_features(location: str | Path) -> list[Feature]:
    """Load a deliberately small, reviewable feature vocabulary from JSON."""
    try:
        raw = json.loads(Path(location).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read feature config: {location}") from error
    values = raw.get("features") if isinstance(raw, dict) else raw
    if not isinstance(values, list) or not values:
        raise ValueError("feature config requires a non-empty features array")
    result: list[Feature] = []
    ids: set[str] = set()
    for index, entry in enumerate(values, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"feature {index} must be an object")
        feature_id, title, keywords = entry.get("id"), entry.get("title"), entry.get("keywords")
        if not isinstance(feature_id, str) or not feature_id.strip():
            raise ValueError(f"feature {index} requires a non-empty id")
        if feature_id in ids:
            raise ValueError(f"feature id is duplicated: {feature_id}")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"feature {feature_id} requires a non-empty title")
        if not isinstance(keywords, list) or not keywords or any(not isinstance(word, str) or not word.strip() for word in keywords):
            raise ValueError(f"feature {feature_id} requires non-empty keywords")
        ids.add(feature_id)
        result.append(Feature(feature_id, title.strip(), tuple(word.strip() for word in keywords)))
    return result
