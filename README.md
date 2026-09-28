# One Bangkok LLM Digests

Stack-agnostic local CLI that converts selected source repositories into deterministic, review-first LLM digests. It supports mixed codebases such as React, Next.js, NestJS, React Native, .NET, Go, Java, and Python without framework-specific parsing.

It is not a replacement for RAG/Graph. Use its reviewed Chat Messages JSONL output to teach a model One Bangkok terminology, answer style, debugging patterns, and retrieval behaviour. Keep changing code knowledge in RAG and Graph.

For the current end-to-end local training workflow, artifacts, commands,
evaluation interpretation, and runtime RAG architecture, see
[Local One Bangkok AI Assistant fine-tuning guide](docs/LOCAL_ONE_BANGKOK_AI_ASSISTANT_FINE_TUNING.md).
The evidence-based POC snapshot follows the team's Scroll record format:
[local AI assistant fine-tuning POC](docs/20260928033247-local-one-bangkok-ai-assistant-poc.md).

## Quick start

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
cp config/repos.example.json config/repos.json
# Edit local repository paths and selection globs in config/repos.json.
obk-llm-digests validate --config config/repos.json
obk-llm-digests digest --config config/repos.json --output data/digest
```

The digest command writes:

```text
data/digest/
  chunks.jsonl              source chunks with file, line, hash, and Git metadata
  digest.md                 tagged text representation for LLM/RAG consumption
  review-candidates.jsonl   prompts that require a human-reviewed answer
  manifest.json             content hashes for incremental re-runs
  security-report.json      excluded path/reason only; never secret values
```

## Generate more review drafts with a local model

Use an Ollama model to turn source chunks into additional Q&A drafts. This does not create training-ready records: every generated answer stays `needs_human_review` and must be checked before approval.

```sh
# Start Ollama and confirm the chosen model is installed first.
ollama serve
obk-llm-digests generate-drafts \
  --digest data/digest \
  --output data/generated-drafts.jsonl \
  --model qwen3:1.7b \
  --repository booking-api \
  --existing data/reviewed.jsonl \
  --limit 100
```

For another OpenAI-compatible local endpoint, set `--provider openai --base-url http://host:port/v1`. Start with 25–100 records per repository and review the result before generating a larger batch.

Use `--append --output data/reviewed.jsonl` only when you want to add generated drafts to the existing review queue. The command deduplicates source chunks already present in that output file.

## Graph-guided cross-service drafts

Graphify supplies relationships while source chunks supply the code evidence. Build context packages from `graph.json` first, then generate architecture/debug-flow drafts from those packages:

```sh
obk-llm-digests graph-context \
  --graph /path/to/one-bangkok-graph/graph.json \
  --digest data/digest \
  --output data/graph-contexts.jsonl \
  --hops 1 \
  --relation calls \
  --limit 100

obk-llm-digests generate-graph-drafts \
  --contexts data/graph-contexts.jsonl \
  --output data/reviewed.jsonl \
  --append \
  --model qwen3:1.7b \
  --limit 25
```

When building a limited cross-service training set, add `--balanced-by-repository`. It selects graph chunks round-robin across repositories before applying `--limit`, preventing an alphabetically first service from consuming every record.

```sh
obk-llm-digests graph-chunks \
  --graph /path/to/one-bangkok-graph/graph.json \
  --digest data/digest \
  --output data/graph-chunks-balanced.jsonl \
  --hops 1 \
  --max-related-chunks 2 \
  --balanced-by-repository \
  --limit 600
```

Use one hop for focused controller/service/API flows and two hops only for selected paths. The graph parser accepts the standard `nodes`/`edges` shape and common node location fields (`source_location`, `location`, `path`, or `file`). If Graphify output uses another schema, inspect a sample before generating a large batch.

## Feature-targeted Q&A drafts

`config/features.json` defines the business features and the reviewable search terms that identify their implementation. The included configuration covers Amenity Booking (Retail/Workplace), Visitor Pass, Workplace Role Management, Authentication, and Notification. Edit its keywords to match the actual names used in each service.

First create `graph-chunks` from a complete digest, then generate drafts. The model receives matching source chunks plus their graph relationships; it cannot use a feature name as evidence. Each output remains `needs_human_review`.

```sh
obk-llm-digests generate-feature-drafts \
  --contexts data/graph-chunks.jsonl \
  --features config/features.json \
  --output data/feature-drafts.jsonl \
  --model qwen3:1.7b \
  --limit-per-feature 20
```

Without `--feature`, the command generates Q&A for **every feature in the JSON configuration**. Use `--all-features-from-config` when you want to make that intent explicit in a script or CI job; it cannot be combined with `--feature`. List the active configuration before a run:

```sh
obk-llm-digests list-features --features config/features.json
```

Generate only selected features by repeating `--feature`, for example `--feature amenity-booking --feature workplace-role`. Add `--append` to preserve prior records and avoid regenerating the same feature/source context.

Ollama is local by default. Use `--provider openai` for a Chat-Completions-compatible local endpoint. For the hosted OpenAI Responses API (for example, `gpt-5.6-terra`), use `--provider openai-responses --base-url https://api.openai.com/v1` and export `OPENAI_API_KEY` in the shell; the key is never written to configuration or output files.

### Chunk-first Graph packages

Use `graph-chunks` when each generated Q&A must retain its primary code body as well as related functions/services. It maps Graphify symbols to the exact digest chunk containing their source line, then adds caller/callee chunks through one or two graph hops.

```sh
obk-llm-digests graph-chunks \
  --graph /path/to/one-bangkok-graph/graph.json \
  --digest data/digest \
  --output data/graph-chunks.jsonl \
  --hops 1 \
  --limit 100

obk-llm-digests generate-graph-drafts \
  --contexts data/graph-chunks.jsonl \
  --output data/reviewed.jsonl \
  --append \
  --model qwen3:1.7b \
  --limit 25
```

## Fine-tune handoff

Review candidates and create a separate JSONL file using this schema. `build-sft` accepts only records with `"review_status":"approved"`; do not mark generated drafts approved until a domain owner has checked the cited source.

```json
{"review_status":"approved","messages":[
  {"role":"system","content":"You are a One Bangkok assistant. Cite retrieved sources and do not guess."},
  {"role":"user","content":"What validates a booking request?"},
  {"role":"assistant","content":"The request validates ... based on the reviewed source evidence."}
]}
```

Validate and export only reviewed examples:

```sh
obk-llm-digests build-sft --reviewed data/reviewed.jsonl --output data/one-bangkok-sft.jsonl
```

## Train a local One Bangkok domain model

### One-command Apple Silicon pipeline

Refresh the Graphify topology and source digest, rebuild balanced graph-enriched
contexts, validate/fingerprint the reviewed dataset, prepare the MLX split, then
train and fuse Qwen3 1.7B and Llama 3.2 1B sequentially:

```sh
./scripts/build_all_local_models.sh
```

Use `--prepare-only` to run every source/data preparation gate without starting
training. Use `--skip-graph-update` when the existing `graph.json` is already
current, or `--skip-source-sync` to reuse both digest and graph chunks after an
interrupted model build.

New digest/graph records are review contexts and are never silently promoted to
fine-tune answers. Add a source-grounded answer to `data/sft_data.jsonl` only
after review, then rerun the pipeline. A build fingerprint makes the script
reuse completed models only when the training split and model config are still
identical; stale artifacts are preserved with a `.stale-<timestamp>` suffix.

After training v10, run the held-out repository-routing and TRUE/FALSE checks:

```sh
uv run --offline --with 'mlx-lm[train]' python scripts/evaluate_domain_model.py \
  --model models/go-to-chaorai-qwen3-1.7b-quality-v10-fused \
  --eval data/go-to-chaorai-v10-classification-eval.jsonl \
  --output data/go-to-chaorai-qwen3-v10-classification-results.json
```

The evaluator loads the model once, uses deterministic decoding, validates the
first binary label plus required/forbidden terms and repository ownership, and
returns a non-zero exit status when any held-out case fails.

The repository now includes supervised fine-tuning via a **LoRA adapter** on `Qwen/Qwen3-1.7B`. LoRA preserves the base model and trains only a small domain adapter, making versioning and rollback practical. Fine-tune reviewed terminology, response style, and stable workflows; use Graph/RAG at runtime for changing code facts.

Only train `data/one-bangkok-sft.jsonl` produced by `build-sft`. Never train raw code chunks or `needs_human_review` drafts.

```sh
python -m pip install -e '.[training]'

# Validate data only. No model download or training.
python scripts/train_lora.py \
  --dataset data/one-bangkok-sft.jsonl \
  --output models/go-to-chaorai-lora \
  --dry-run

# Standard LoRA: suitable starting mode for Apple Silicon.
python scripts/train_lora.py \
  --dataset data/one-bangkok-sft.jsonl \
  --base-model Qwen/Qwen3-1.7B \
  --output models/go-to-chaorai-lora \
  --epochs 3 \
  --batch-size 1 \
  --gradient-accumulation 8 \
  --max-length 2048
```

For an NVIDIA CUDA machine, QLoRA can reduce VRAM consumption:

```sh
python -m pip install -e '.[training,qlora]'
python scripts/train_lora.py --dataset data/one-bangkok-sft.jsonl --output models/go-to-chaorai-lora --quantization 4bit
```

The output contains adapter weights, tokenizer, checkpoints, and `training-manifest.json` with the dataset hash and hyperparameters. Merge only if a deployment requires a standalone Transformers model:

```sh
python scripts/merge_lora.py \
  --base-model Qwen/Qwen3-1.7B \
  --adapter models/go-to-chaorai-lora \
  --output models/go-to-chaorai-merged
```

## Refresh source-grounded Workplace data

Replace the old generic Workplace Role Management records with the curated
APP/BMS/CMS/Notification dataset:

```sh
.venv/bin/python scripts/refresh_workplace_sft.py \
  --dataset data/sft_data.jsonl \
  --count 1200
```

The command is safe to rerun: it replaces its previous Workplace output instead
of appending duplicates. It covers identity linkage, Tenant/Member authorization,
member sync and offboarding, What's Happening, Call Elevator, Visitor Pass, AQI,
Building Service, CMS role boundaries, Kafka, Notification, observability, QA,
debugging, security review, and explicit abstention where source evidence is absent.

Refresh the source-grounded IAM dataset in the same way:

```sh
.venv/bin/python scripts/refresh_iam_sft.py \
  --dataset data/sft_data.jsonl \
  --count 1600
```

The IAM set covers login strategies, JWT and refresh behavior, OTP/2FA,
Identity and External Identity, Workplace binding and offboarding, attached
permissions, SSO, devices/FCM, Notification recipient synchronization, QR-token
boundaries, cache consistency, security review, and evidence-based abstention.

Validate conversion to Chat Messages JSONL before training:

```sh
.venv/bin/python scripts/prepare_instruction_sft.py \
  --input data/sft_data.jsonl \
  --output data/workplace-training.jsonl
```

## Detailed review workflow

Each draft record remains `needs_human_review`. A reviewer verifies the cited source, revises the answer, then adds a non-empty `reviewer`, ISO-8601 `reviewed_at`, and changes the status to `approved`.

Run the review gate before fine-tuning:

```sh
obk-llm-digests review \
  --reviewed data/reviewed.jsonl \
  --digest data/digest \
  --report data/review-report.json
```

The report counts status and repository coverage, and flags stale source hashes, missing source evidence, malformed messages, missing approval metadata, draft-marked approved answers, duplicate questions, and missing visible citations. Warnings need reviewer judgement; errors block the command and SFT export.

## Security and selection

- The tool only reads local paths in the JSON config; it never clones repositories or manages Git credentials.
- `.env`, private keys, credential files, likely secret values, binary files, dependencies, build output, source maps, and lockfiles are excluded.
- The report includes only repository label, relative path, and exclusion reason.
- Use `include` / `exclude` globs to reduce the selected scope. Add `text_extensions` or set `allow_unknown_text` when a text extension is not in the default allowlist.
# ob-llm-fine-tune
