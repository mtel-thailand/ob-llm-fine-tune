"""Validation helpers for reviewed chat-message supervised fine-tuning data."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def load_sft_records(location: str | Path) -> list[dict]:
    path = Path(location)
    if not path.is_file():
        raise ValueError(f"SFT dataset not found: {path}")
    records: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            messages = json.loads(line)["messages"]
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(f"SFT line {number}: expected a JSON object with messages") from error
        if not isinstance(messages, list) or not messages:
            raise ValueError(f"SFT line {number}: messages must be a non-empty array")
        if any(not isinstance(item, dict) or item.get("role") not in {"system", "user", "assistant"}
               or not isinstance(item.get("content"), str) or not item["content"].strip() for item in messages):
            raise ValueError(f"SFT line {number}: every message needs a supported role and non-empty content")
        if not {"system", "user", "assistant"}.issubset({item["role"] for item in messages}):
            raise ValueError(f"SFT line {number}: system, user, and assistant roles are required")
        if messages[-1]["role"] != "assistant":
            raise ValueError(f"SFT line {number}: final message must be the target assistant answer")
        records.append({"messages": messages})
    if not records:
        raise ValueError("SFT dataset has no usable records")
    return records


def dataset_sha256(location: str | Path) -> str:
    return hashlib.sha256(Path(location).read_bytes()).hexdigest()
