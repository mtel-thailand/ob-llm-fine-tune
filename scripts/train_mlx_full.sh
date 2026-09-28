#!/usr/bin/env bash
# Build compact label-preserving MLX data from the full corpus, then train one pass.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

python3 scripts/prepare_mlx_compact_data.py \
  --input data/sft_data.jsonl \
  --output-dir data/mlx-full-20000-compact \
  --valid-count 1000

uv run --with 'mlx-lm[train]' mlx_lm.lora \
  --config config/mlx-qwen3-1.7b-full-v4.yaml
