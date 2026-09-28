#!/usr/bin/env bash
# Refresh source/graph artifacts, validate and prepare the reviewed v10 dataset,
# then train and fuse Qwen3 1.7B and Llama 3.2 1B sequentially.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PREPARE_ONLY=false
SYNC_SOURCES=true
UPDATE_GRAPH=true

usage() {
  cat <<'EOF'
Usage: ./scripts/build_all_local_models.sh [options]

With no options, the script refreshes source and graph artifacts, prepares the
reviewed dataset, trains both models sequentially, and fuses both models.

Options:
  --prepare-only      Refresh sources and prepare the shared v10 dataset, then stop.
  --skip-source-sync  Reuse the existing digest and graph-chunks artifacts.
  --skip-graph-update Rebuild digest/graph-chunks but reuse the existing graph.json.
  -h, --help          Show this help message.
EOF
}

while (($# > 0)); do
  case "$1" in
    --prepare-only)
      PREPARE_ONLY=true
      ;;
    --skip-source-sync)
      SYNC_SOURCES=false
      UPDATE_GRAPH=false
      ;;
    --skip-graph-update)
      UPDATE_GRAPH=false
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

PYTHON="$ROOT/.venv/bin/python"
WORKSPACE_ROOT="$(cd "$ROOT/../.." && pwd)"
CONFIG="$ROOT/config/repos.json"
DATASET="$ROOT/data/sft_data.jsonl"
ANCHOR_SCRIPT="$ROOT/scripts/add_direct_domain_anchors.py"
CLASSIFICATION_SCRIPT="$ROOT/scripts/add_classification_binary_sft.py"
GUARDRAIL_SCRIPT="$ROOT/scripts/add_grounding_guardrails_sft.py"
DIGEST="$ROOT/data/digest"
GRAPH_FILE="${OBK_GRAPH_FILE:-$WORKSPACE_ROOT/one-bangkok-graph/graph.json}"
GRAPH_DIR="$(dirname "$GRAPH_FILE")"
GRAPH_CHUNKS="$ROOT/data/graph-chunks.jsonl"
SOURCE_SYNC_REPORT="$ROOT/data/source-sync-report-v10.json"
GRAPH_CHUNK_LIMIT="${OBK_GRAPH_CHUNK_LIMIT:-5000}"
CHAT_DATA="$ROOT/data/go-to-chaorai-quality-v10-chat.jsonl"
MLX_DATA="$ROOT/data/mlx-quality-v10"
QWEN_CONFIG="$ROOT/config/mlx-qwen3-1.7b-quality-v10.yaml"
LLAMA_CONFIG="$ROOT/config/mlx-llama3.2-1b-quality-v10.yaml"
QWEN_REPO="mlx-community/Qwen3-1.7B-4bit-AWQ"
LLAMA_REPO="mlx-community/Llama-3.2-1B-Instruct-4bit"
QWEN_ADAPTER="$ROOT/models/go-to-chaorai-qwen3-1.7b-quality-v10-lora"
LLAMA_ADAPTER="$ROOT/models/go-to-chaorai-llama-3.2-1b-quality-v10-lora"
QWEN_FUSED="$ROOT/models/go-to-chaorai-qwen3-1.7b-quality-v10-fused"
LLAMA_FUSED="$ROOT/models/go-to-chaorai-llama-3.2-1b-quality-v10-fused"

if [[ ! -x "$PYTHON" ]]; then
  echo "error: $PYTHON not found; run 'uv sync' in $ROOT first" >&2
  exit 2
fi
if [[ ! -s "$DATASET" ]]; then
  echo "error: dataset not found or empty: $DATASET" >&2
  exit 2
fi
if [[ "$PREPARE_ONLY" == false ]] && pgrep -f '[m]lx_lm\.lora' >/dev/null 2>&1; then
  echo "error: another mlx_lm.lora process is already running; stop it before this sequential build" >&2
  exit 2
fi

run_cli() {
  PYTHONPATH="$ROOT/src" "$PYTHON" -m obk_llm_digests.cli "$@"
}

echo "==> 1/11 validate repository configuration"
run_cli validate --config "$CONFIG"

if [[ "$SYNC_SOURCES" == true ]]; then
  echo "==> 2/11 refresh source knowledge"
  if [[ "$UPDATE_GRAPH" == true ]]; then
    if [[ ! -s "$GRAPH_FILE" ]]; then
      echo "error: graph not found: $GRAPH_FILE" >&2
      echo "run a full graphify build before using the one-command pipeline" >&2
      exit 2
    fi
    if ! command -v graphify >/dev/null 2>&1; then
      echo "error: graphify is not installed; use --skip-graph-update to reuse $GRAPH_FILE" >&2
      exit 2
    fi
    echo "    updating Graphify topology from $WORKSPACE_ROOT"
    (
      cd "$WORKSPACE_ROOT"
      GRAPHIFY_OUT="$GRAPH_DIR" graphify update .
    )
  else
    echo "    reusing existing graph: $GRAPH_FILE"
  fi

  echo "    rebuilding incremental source digest"
  run_cli digest --config "$CONFIG" --output "$DIGEST"
  run_cli validate --config "$CONFIG" --output "$DIGEST"

  echo "    rebuilding balanced graph-enriched source contexts"
  run_cli graph-chunks \
    --graph "$GRAPH_FILE" \
    --digest "$DIGEST" \
    --output "$GRAPH_CHUNKS" \
    --hops 1 \
    --max-related-chunks 4 \
    --balanced-by-repository \
    --limit "$GRAPH_CHUNK_LIMIT"
else
  echo "==> 2/11 reuse existing source knowledge (--skip-source-sync)"
  run_cli validate --config "$CONFIG" --output "$DIGEST"
  if [[ ! -s "$GRAPH_CHUNKS" ]]; then
    echo "error: graph chunks not found or empty: $GRAPH_CHUNKS" >&2
    exit 2
  fi
fi

echo "==> 3/11 refresh direct One Bangkok domain anchors"
"$PYTHON" "$ANCHOR_SCRIPT" --dataset "$DATASET"
"$PYTHON" "$CLASSIFICATION_SCRIPT" \
  --dataset "$DATASET" \
  --eval-output "$ROOT/data/go-to-chaorai-v10-classification-eval.jsonl"
"$PYTHON" "$GUARDRAIL_SCRIPT"

echo "==> 4/11 validate and fingerprint the reviewed instruction dataset"
"$PYTHON" scripts/validate_instruction_dataset.py \
  --dataset "$DATASET" \
  --digest "$DIGEST" \
  --graph-chunks "$GRAPH_CHUNKS" \
  --output "$SOURCE_SYNC_REPORT"

echo "==> 5/11 create chat SFT with direct curated examples"
PYTHONPATH="$ROOT/src" "$PYTHON" scripts/prepare_instruction_sft.py \
  --input "$DATASET" \
  --output "$CHAT_DATA" \
  --add-direct-curated \
  --direct-repeat 4 \
  --anchor-repeat 16

echo "==> 6/11 create deterministic MLX train/validation split"
PYTHONPATH="$ROOT/src" "$PYTHON" scripts/prepare_mlx_data.py \
  --input "$CHAT_DATA" \
  --output-dir "$MLX_DATA" \
  --valid-count 100 \
  --seed 20260924 \
  --keep-direct-in-train

if [[ "$PREPARE_ONLY" == true ]]; then
  echo
  echo "Preparation complete; training skipped (--prepare-only)."
  echo "Chat dataset: $CHAT_DATA"
  echo "MLX dataset:  $MLX_DATA"
  echo "Source report: $SOURCE_SYNC_REPORT"
  echo "Graph contexts requiring review: $GRAPH_CHUNKS"
  exit 0
fi

resolve_snapshot() {
  local cache_name="$1"
  local repo_id="$2"
  local cache_root="${HF_HOME:-${HOME}/.cache/huggingface}/hub/$cache_name/snapshots"
  local candidate=""
  if [[ -d "$cache_root" ]]; then
    for directory in "$cache_root"/*; do
      if [[ -f "$directory/model.safetensors" && -f "$directory/config.json" ]]; then
        candidate="$directory"
        break
      fi
    done
  fi
  if [[ -n "$candidate" ]]; then
    printf '%s\n' "$candidate"
  else
    printf '%s\n' "$repo_id"
  fi
}

training_fingerprint() {
  local config="$1"
  "$PYTHON" -c 'import hashlib,sys; h=hashlib.sha256(); [(h.update(open(p,"rb").read()),h.update(b"\0")) for p in sys.argv[1:]]; print(h.hexdigest())' \
    "$config" "$MLX_DATA/train.jsonl" "$MLX_DATA/valid.jsonl"
}

manifest_fingerprint() {
  local manifest="$1"
  if [[ ! -s "$manifest" ]]; then
    return
  fi
  "$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8")).get("training_fingerprint",""))' "$manifest" 2>/dev/null || true
}

write_build_manifest() {
  local directory="$1"
  local label="$2"
  local fingerprint="$3"
  "$PYTHON" -c 'import json,sys,datetime,pathlib; p=pathlib.Path(sys.argv[1]); p.mkdir(parents=True,exist_ok=True); value={"model":sys.argv[2],"training_fingerprint":sys.argv[3],"built_at":datetime.datetime.now(datetime.timezone.utc).isoformat()}; (p/"build-manifest.json").write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8")' \
    "$directory" "$label" "$fingerprint"
}

archive_stale_directory() {
  local directory="$1"
  if [[ -e "$directory" ]]; then
    local archived="${directory}.stale-$(date -u +%Y%m%d-%H%M%S)"
    echo "    preserving stale artifact as $archived"
    mv "$directory" "$archived"
  fi
}

train_if_needed() {
  local label="$1"
  local config="$2"
  local adapter="$3"
  local fingerprint="$4"
  local recorded
  recorded="$(manifest_fingerprint "$adapter/build-manifest.json")"
  if [[ -s "$adapter/adapters.safetensors" && "$recorded" == "$fingerprint" ]]; then
    echo "==> $label adapter already complete; skipping training"
    return
  fi
  if [[ -e "$adapter" ]]; then
    echo "==> $label adapter is incomplete or belongs to different data/config"
    archive_stale_directory "$adapter"
  fi
  echo "==> training $label (this can take several hours)"
  # The training environment is already resolved before a long run starts.
  # Offline mode prevents a completed multi-hour training job from failing at
  # the next step only because PyPI or DNS is temporarily unavailable.
  uv run --offline --with 'mlx-lm[train]' mlx_lm.lora --config "$config"
  if [[ ! -s "$adapter/adapters.safetensors" ]]; then
    echo "error: $label training ended without $adapter/adapters.safetensors" >&2
    exit 2
  fi
  write_build_manifest "$adapter" "$label" "$fingerprint"
}

fuse_if_needed() {
  local label="$1"
  local base="$2"
  local adapter="$3"
  local output="$4"
  local fingerprint="$5"
  local recorded
  recorded="$(manifest_fingerprint "$output/build-manifest.json")"
  if [[ -s "$output/model.safetensors" && "$recorded" == "$fingerprint" ]]; then
    echo "==> $label fused model already complete; skipping fuse"
    return
  fi
  if [[ -e "$output" ]]; then
    echo "==> $label fused model is incomplete or belongs to different data/config"
    archive_stale_directory "$output"
  fi
  echo "==> fusing standalone $label model"
  # Reuse the exact cached MLX environment used for training. Using a different
  # extra here causes uv to resolve PyPI again even when all code is local.
  uv run --offline --with 'mlx-lm[train]' mlx_lm.fuse \
    --model "$base" \
    --adapter-path "$adapter" \
    --save-path "$output"
  if [[ ! -s "$output/model.safetensors" ]]; then
    echo "error: fused $label model was not created" >&2
    exit 2
  fi
  write_build_manifest "$output" "$label" "$fingerprint"
}

echo "==> 7/11 train Qwen3 1.7B"
QWEN_FINGERPRINT="$(training_fingerprint "$QWEN_CONFIG")"
train_if_needed "Qwen3 1.7B" "$QWEN_CONFIG" "$QWEN_ADAPTER" "$QWEN_FINGERPRINT"
echo "==> 8/11 fuse Qwen3 1.7B"
QWEN_BASE="$(resolve_snapshot 'models--mlx-community--Qwen3-1.7B-4bit-AWQ' "$QWEN_REPO")"
fuse_if_needed "Qwen3 1.7B" "$QWEN_BASE" "$QWEN_ADAPTER" "$QWEN_FUSED" "$QWEN_FINGERPRINT"

echo "==> release Qwen references before the next trainer"
sleep 2

echo "==> 9/11 train Llama 3.2 1B"
LLAMA_FINGERPRINT="$(training_fingerprint "$LLAMA_CONFIG")"
train_if_needed "Llama 3.2 1B" "$LLAMA_CONFIG" "$LLAMA_ADAPTER" "$LLAMA_FINGERPRINT"
echo "==> 10/11 fuse Llama 3.2 1B"
LLAMA_BASE="$(resolve_snapshot 'models--mlx-community--Llama-3.2-1B-Instruct-4bit' "$LLAMA_REPO")"
fuse_if_needed "Llama 3.2 1B" "$LLAMA_BASE" "$LLAMA_ADAPTER" "$LLAMA_FUSED" "$LLAMA_FINGERPRINT"

echo "==> 11/11 complete"
echo "Qwen:  $QWEN_FUSED"
echo "Llama: $LLAMA_FUSED"
echo "Eval:  $ROOT/data/go-to-chaorai-v10-eval.jsonl"
echo "RAG/graph contexts: $GRAPH_CHUNKS"
echo "Source sync report: $SOURCE_SYNC_REPORT"
