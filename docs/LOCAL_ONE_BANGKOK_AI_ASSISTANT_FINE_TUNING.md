# Local One Bangkok AI Assistant fine-tuning guide

## Purpose

The Local One Bangkok AI Assistant is an internal assistant for Product Owners, QA, and
engineers. It explains approved One Bangkok business flows, answers scoped
engineering questions, and helps investigate source-backed issues.

Project repository: [mtel-thailand/ob-llm-fine-tune](https://github.com/mtel-thailand/ob-llm-fine-tune).

It is **not** a replacement for source retrieval. Fine-tuning teaches the
assistant One Bangkok terminology, answer style, evidence boundaries, and
stable product concepts. RAG and Graphify provide current code facts at runtime.

```text
Local repositories ──> digest ──> graph-enriched contexts ──> reviewed SFT
                                                            │
                                                            ├─> LoRA training
                                                            └─> evaluation

Runtime question ──> feature/router ──> RAG + graph context ──> local model
```

## Supporting knowledge systems: Abdul Maker, Graphify, and one-bangkok-rag

The local assistant uses three separate systems. They complement each other;
none is a replacement for the other.

| System | Workspace/location | Primary job | Does not do |
| --- | --- | --- | --- |
| Abdul Maker | `../abdul-maker` | Workspace shell and repeatable graph/RAG refresh workflow | It is not an AI agent and does not answer users directly |
| Graphify / one-bangkok-graph | `../one-bangkok-graph/graph.json` | Static code topology: symbols, imports, calls, and related nodes | It does not prove that a runtime call succeeded |
| one-bangkok-rag (`obk-rag`) | `../obk-rag/index.db` | Hybrid source retrieval across One Bangkok repositories | It does not generate an answer or replace source review |
| Local One Bangkok AI Assistant | this repository + fused MLX model | Explain retrieved evidence in an appropriate One Bangkok style | It must not invent absent code facts |

`abdul-marker` in earlier discussions refers to the **Abdul Maker** workspace
at `../abdul-maker`. Its `sync-graph-rag.sh` script coordinates an incremental
Graphify update and an `obk-rag` update. It does not create a model, fine-tune
a model, or persist graph data in MinIO by itself.

### Knowledge lifecycle

```text
Application repositories change
  -> Abdul Maker runs Graphify update
  -> one-bangkok-graph/graph.json is refreshed
  -> obk-rag re-indexes only changed source files
  -> optional publish sends index.db + checksum manifest to private MinIO
  -> each developer pulls the verified index.db when needed
  -> runtime RAG retrieves relevant chunks and graph neighbours
  -> local model explains only that retrieved evidence
```

The graph and index should be refreshed after code changes. Fine-tuning should
be refreshed only after stable, reviewed domain knowledge changes; it is not a
per-commit index update mechanism.

### Abdul Maker workspace setup and refresh

The intended sibling layout is:

```text
/path/to/one-bangkok-workspace/
  abdul-maker/                 # workspace shell and sync script
  one-bangkok-graph/           # Graphify output, including graph.json
  obk-rag/                     # one-bangkok-rag tool and index.db
  one-bangkok-llm-digests/     # this training/documentation project
  one-bangkok-app/             # APP repository
  obk-mtel-iam/                # IAM repository
  obk-mtel-bms/                # BMS repository
  ...
```

Abdul Maker requires an existing full Graphify build. Its incremental script
cannot create a missing `graph.json`; a full `/graphify` build in an agent host
is required first because semantic document extraction needs agent-dispatched
work. After `graph.json` exists, use:

```bash
cd /path/to/one-bangkok-workspace/abdul-maker

# AST/code topology update plus incremental RAG update; no LLM graph labels.
./scripts/sync-graph-rag.sh --no-label

# Optional: label newly discovered graph communities when an LLM key is set.
./scripts/sync-graph-rag.sh

# Optional: regenerate every existing community label.
./scripts/sync-graph-rag.sh --relabel-all
```

The script loads `abdul-maker/.envrc`. Set `GRAPHIFY_OUT` there to the desired
graph output directory, for example:

```bash
export GRAPHIFY_OUT=one-bangkok-graph
```

Non-code files such as `.gitignore` or `.envrc.example` can be reported as
skipped. This is expected: they are not supported code inputs. A message that
no topology changed means the current code update had no structural graph
change; it does **not** mean RAG was rebuilt or that documentation semantics
were extracted.

### one-bangkok-rag index and MinIO distribution

`obk-rag` stores source chunks, FTS5 search data, vectors, file hashes, and
Graphify node links in one private SQLite file, `index.db`. It uses:

* SQLite FTS5 keyword search;
* on-device `BAAI/bge-small-en-v1.5` embeddings for semantic search;
* reciprocal-rank fusion to combine keyword and vector results;
* optional one- or two-hop Graphify expansion from a retrieved code node.

The database contains source snippets. Do not commit it to Git or expose it in
a public bucket. The published copy belongs in the private MinIO bucket
`one-bangkok-rag`; MinIO distributes a binary artifact, not training data and
not model weights.

Install/query from the `obk-rag` repository:

```bash
cd /path/to/one-bangkok-workspace/obk-rag

# Indexing installation includes torch and sentence-transformers.
uv sync --extra index

# Query-only host can normally use the lighter dependency set.
# uv sync

# Required only for MinIO pull/publish; never commit these values.
source ../.envrc

# Pull the current private index and verify its SHA-256 manifest.
uv run obk-rag pull --if-changed

# Confirm index availability and repository/chunk counts.
uv run obk-rag stats
```

If MinIO has no published index, or a developer intentionally needs a local
rebuild:

```bash
# Re-index only files whose content hash changed.
uv run obk-rag update

# Full rebuild across discovered sibling repositories.
uv run obk-rag index --full

# Build only one repository when investigating a targeted change.
uv run obk-rag index --repo obk-mtel-bms

# Publish the private index.db and SHA-256 manifest to MinIO.
uv run obk-rag publish
```

`pull` verifies the checksum before replacing the local index. `publish` and
`pull` require `MINIO_S3_ENDPOINT`, `MINIO_ROOT_USER`, and
`MINIO_ROOT_PASSWORD` in environment variables. Prefer a scoped MinIO service
account over broad root credentials when the deployment is hardened.

### Search, graph expansion, and MCP usage

For a quick terminal investigation:

```bash
cd /path/to/one-bangkok-workspace

# Hybrid keyword + semantic search across the index.
uv run --project obk-rag obk-rag search "Visitor Pass invitation email" --json

# Retrieve source and attach Graphify neighbours such as callers/imports.
uv run --project obk-rag obk-rag search "Visitor Pass invitation email" --expand --json

# Limit a query when the owning service is already known.
uv run --project obk-rag obk-rag search "pass confirmation" --repo obk-mtel-bms --show 12

# Run read-only MCP stdio tools: search_code, hybrid_query, and stats.
uv run --project obk-rag obk-rag serve
```

`search_code` returns ranked code chunks with `repo/path:start-end`, a symbol
when known, ranker information, and Graphify node identity. `hybrid_query`
adds graph neighbours. Results are evidence to inspect, not a conclusion by
themselves: snippets can be truncated, and an edge only establishes a static
relationship.

### Passing RAG context to the local model

This repository's `ask-rag` command delegates retrieval to `obk-rag` and gives
the selected source chunks to a fused MLX model. It does not call a hosted LLM.

```bash
cd /path/to/one-bangkok-workspace/OB-Internal-AI/one-bangkok-llm-digests

PYTHONPATH=src uv run --offline --with mlx-lm --with-editable . \
  obk-llm-digests ask-rag \
  --obk-rag-project /path/to/one-bangkok-workspace/obk-rag \
  --model models/go-to-chaorai-qwen3-1.7b-quality-v10-fused \
  --question "Explain the Visitor Pass flow for an operations user." \
  --limit 8 \
  --max-context-chars 28000 \
  --max-tokens 900 \
  --temp 0.1
```

At runtime the responsibilities are deliberate:

1. The router chooses the feature/repositories.
2. `obk-rag` finds current source chunks and graph neighbours.
3. The local model explains those chunks in plain language.
4. The answer must cite the returned source locations and state an evidence
   gap rather than fill it from generic knowledge.

## Scope and evidence policy

The assistant is restricted to One Bangkok. The configured repositories are:

| Repository label | Main responsibility |
| --- | --- |
| `mobile-app` | React Native user journeys and client-side gates |
| `iam` | Authentication, identity, sessions, tokens, external identity |
| `bms` | Workplace members, roles, visitor/pass domain, FS integration |
| `booking-api` | Amenity Booking lifecycle and resource policy |
| `notification` | Message templates, recipient projections, channels/providers |
| `cms` | Next.js back-office workflows |

Rules for all data and runtime answers:

1. Do not invent routes, tables, Kafka events, logs, external provider
   responses, delivery status, QR behavior, or physical-access outcomes.
2. A Graphify edge is structural code evidence, not proof that a production call
   completed.
3. A Kafka publication does not prove consumption, provider acceptance, or email
   delivery.
4. When retrieved context does not establish a requested fact, say that more
   source context is required.
5. Do not replace a One Bangkok term with a generic industry meaning. For
   example, Visitor Pass is a Workplace visitor-invitation flow, not a tourism,
   hotel, attraction, or discount pass.

## Current dataset snapshot

The current canonical source is `data/sft_data.jsonl`. This is curated training
data, not raw code and not an automatic model output.

| Artifact | Current result |
| --- | ---: |
| Canonical SFT records | 1,428 |
| Unique instructions | 1,428 |
| Records with source citations | 1,308 |
| Chat-formatted SFT records | 2,484 |
| MLX training records | 2,384 |
| MLX validation records | 100 |
| Digest source files | 3,271 |
| Digest chunks | 6,264 |
| Graph-enriched contexts | 3,865 |

The dataset validator result is stored in
`data/source-sync-report-v10.json`. At the latest preparation run it reported
zero errors and zero warnings.

### Important curated reinforcement

The preparation pipeline regenerates these deterministic records before every
training run:

- Direct One Bangkok anchors for Visitor Pass and Sync Member.
- Repository-routing classification examples.
- TRUE/FALSE evidence-boundary examples.
- Unsupported-claim guardrails for Visitor Pass and Amenity Booking.

The direct anchors are repeated more often in the chat training set. This is
intentional: small 1B–1.7B models otherwise tend to use a generic internet
meaning for terms such as “Visitor Pass.”

## Prerequisites

This guide targets Apple Silicon with MLX and a local Python virtual
environment.

```bash
cd /path/to/one-bangkok-workspace/OB-Internal-AI/one-bangkok-llm-digests

uv sync
```

The base models are cached by Hugging Face/MLX after their first download. A
later fine-tune normally reuses that cache. `--offline` prevents a completed
local workflow from failing only because PyPI/DNS is temporarily unavailable.

## Full build: source refresh, data preparation, train, and fuse

Use this when source repositories or Graphify output changed:

```bash
./scripts/build_all_local_models.sh
```

The script works sequentially to avoid running two MLX trainers at once:

1. Validate `config/repos.json`.
2. Update Graphify topology.
3. Rebuild the incremental source digest.
4. Build graph-enriched contexts.
5. Regenerate anchors, classification examples, and evidence guardrails.
6. Validate and fingerprint the dataset.
7. Convert instruction records to Chat Messages JSONL.
8. Make a deterministic train/validation split.
9. Train and fuse Qwen3 1.7B.
10. Train and fuse Llama 3.2 1B.

### Faster reruns

Use existing digest and graph context when only data preparation or a model
configuration changed:

```bash
./scripts/build_all_local_models.sh --skip-source-sync
```

Run every source/data validation stage but do not train:

```bash
./scripts/build_all_local_models.sh --prepare-only --skip-source-sync
```

The pipeline fingerprints the model configuration plus `train.jsonl` and
`valid.jsonl`. If either changes, it preserves the old model directory as
`.stale-<timestamp>` and trains/fuses a replacement. A `.stale-*` directory is
an old artifact, not the latest model.

## Current model configurations

| Model | Base model | Fine-tune | Batch | Sequence length | Training steps |
| --- | --- | --- | ---: | ---: | ---: |
| Qwen | `mlx-community/Qwen3-1.7B-4bit-AWQ` | LoRA, all 28 layers | 2 | 1,024 | 2,384 |
| Llama | `mlx-community/Llama-3.2-1B-Instruct-4bit` | LoRA, 16 layers | 2 | 1,024 | 2,384 |

With 2,384 training records and batch size 2, 2,384 training steps expose the
trainer to approximately two passes over the prepared training split.

## Output artifacts

### Qwen3 1.7B

```text
models/go-to-chaorai-qwen3-1.7b-quality-v10-lora/
  adapters.safetensors       # LoRA adapter only
  build-manifest.json

models/go-to-chaorai-qwen3-1.7b-quality-v10-fused/
  model.safetensors          # standalone fused local model
  tokenizer.json / config.json / generation_config.json
  build-manifest.json
```

### Llama 3.2 1B

```text
models/go-to-chaorai-llama-3.2-1b-quality-v10-lora/
models/go-to-chaorai-llama-3.2-1b-quality-v10-fused/
```

Use the `*-fused` directory for normal local inference. Use the `*-lora`
directory only when you intentionally want to keep the base model and attach
the adapter yourself.

## Test a model manually

Always send the system prompt and use deterministic decoding for a routing or
classification check.

```bash
cd /path/to/one-bangkok-workspace/OB-Internal-AI/one-bangkok-llm-digests

TASK_SYSTEM_PROMPT="$(tr '\n' ' ' < config/go-to-chaorai-system.txt)" \
uv run --offline --with 'mlx-lm[train]' mlx_lm.generate \
  --model models/go-to-chaorai-qwen3-1.7b-quality-v10-fused \
  --system-prompt "$TASK_SYSTEM_PROMPT" \
  --chat-template-config '{"enable_thinking": false}' \
  --max-tokens 80 \
  --temp 0 \
  --prompt "A Visitor Pass defect spans invite creation and visitor email. Which repositories contain the primary evidence? Use exactly this format: Primary: <repositories>."
```

The expected classification is:

```text
Primary: mobile-app, bms, notification
```

To run all held-out routing and binary cases:

```bash
PYTHONPATH=src uv run --offline --with 'mlx-lm[train]' \
  python scripts/evaluate_domain_model.py \
  --model models/go-to-chaorai-qwen3-1.7b-quality-v10-fused \
  --eval data/go-to-chaorai-v10-classification-eval.jsonl \
  --output data/go-to-chaorai-qwen3-v10-classification-results.json \
  --max-tokens 180
```

Run the same command with the Llama fused directory to test Llama.

## Recorded evaluation results and interpretation

The retained historical result files report:

| Model | Held-out cases | Reported pass rate |
| --- | ---: | ---: |
| Qwen3 1.7B v10 fused | 12 | 1/12 (8.3%) |
| Llama 3.2 1B v10 fused | 12 | 4/12 (33.3%) |

The old Llama score was too generous because the earlier evaluator could count
a repository word anywhere in prose. The current evaluator requires an explicit
`Primary:` field for routing answers, so re-run evaluation after rebuilding.

Manual tests also showed both small models can hallucinate nonexistent
repositories or generic product meanings. Therefore these scores must **not**
be treated as production readiness. The model is useful for phrasing,
explanation, and constrained assistance, but not as the authority for exact
repository ownership or current code facts.

## Recommended runtime architecture

For production-like use, do not ask a 1B–1.7B model to remember all source
facts from fine-tuning alone.

```text
User question
  -> deterministic feature/repository routing
  -> obk-rag hybrid retrieval + Graphify expansion
  -> source-grounded prompt with file/line context
  -> fused local assistant model
  -> answer citing sources and declaring evidence gaps
```

Example source-grounded runtime command:

```bash
PYTHONPATH=src uv run --offline --with mlx-lm --with-editable . \
  obk-llm-digests ask-rag \
  --obk-rag-project /path/to/one-bangkok-workspace/obk-rag \
  --model models/go-to-chaorai-qwen3-1.7b-quality-v10-fused \
  --question "Explain the Visitor Pass flow." \
  --limit 8 \
  --max-context-chars 28000 \
  --max-tokens 900 \
  --temp 0.1
```

This does not prove that the model will never hallucinate; it gives it the
current code excerpts that must constrain the response. For strict routing,
return the router's deterministic result before calling the model.

## Updating the knowledge safely

1. Update or clone the approved local repositories.
2. Run `./scripts/build_all_local_models.sh --prepare-only`.
3. Review changes in `data/digest/review-candidates.jsonl` and
   `data/graph-chunks.jsonl`.
4. Add only reviewed, source-backed Q&A to `data/sft_data.jsonl`.
5. Run the dataset validator; do not train when it reports errors.
6. Train and fuse sequentially.
7. Run held-out evaluations and manual business-flow checks.
8. Promote only a fused model with recorded build fingerprint and acceptable
   evaluation/review evidence.

Never train raw repository code or an automatically generated draft without
review. The codebase changes more frequently than a small model should be
fine-tuned; refresh RAG/graph for those changes instead.

## Troubleshooting

| Symptom | Meaning | Action |
| --- | --- | --- |
| `another mlx_lm.lora process is already running` | Another trainer is active | Wait for it to finish or stop the known process before starting the sequential pipeline. |
| `--offline` cannot resolve MLX | MLX package/base model was never cached | Run once with network access, then retry offline. |
| A model directory has `.stale-...` | The pipeline detected a different data/config fingerprint | Use the non-stale fused directory after the new train/fuse completes. |
| Generic tourism/hotel answer for Visitor Pass | Small-model hallucination or missing runtime grounding | Verify the active fused manifest; use direct anchors plus RAG; do not accept the answer as fact. |
| RAG returns no context | Index was not built for the target repositories | Refresh digest/index and check configured repository paths. |
