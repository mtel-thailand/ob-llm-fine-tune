# Local One Bangkok AI Assistant POC: small-model domain assistant with RAG

* Owner: One Bangkok Internal AI team
* Requester: One Bangkok Internal AI project
* Date: 2026-09-28
* Tags: project:one-bangkok, local-llm, fine-tuning, rag, graph, mlx

## POC Overview

| Field | Details |
|---|---|
| Status | Completed |
| Result | Conditionally Successful |
| Environment | Local Apple Silicon development machine |
| Start Date | 2026-09-24 |
| Completion Date | 2026-09-28 |

## Objective and Scope

### Objective

> Can a local LoRA-fine-tuned model with no more than 1.7B parameters provide
> useful, source-grounded One Bangkok assistance for business-flow explanation,
> debugging support, and repository routing when paired with current RAG and
> Graphify context?

### Background

One Bangkok source is distributed between the APP, IAM, BMS, Booking,
Notification, and CMS repositories. A small local model is desirable for low
hardware requirements and internal use, but code and service relationships
change frequently. The POC evaluates a separation of responsibilities:

* reviewed fine-tuning data teaches One Bangkok terms, scope, response style,
  and stable concepts;
* digest, RAG, and Graphify provide current code evidence;
* a deterministic router selects the relevant source scope before generation.

### In Scope

* Local Qwen3 1.7B and Llama 3.2 1B LoRA fine-tuning through MLX.
* Source digest, graph-enriched contexts, curated SFT, and held-out tests.
* One Bangkok Visitor Pass, Amenity Booking, Workplace, IAM, Sync Member, and
  Notification knowledge.
* Local RAG invocation using `obk-rag` and graph-aware source context.
* The six configured POC repositories: APP/mobile-app, IAM, BMS, Booking API,
  Notification, and CMS.

### Out of Scope

* Production hosting, user access control, monitoring, and deployment.
* Training a model larger than 1.7B.
* Treating a model-only answer as proof of current code behavior.
* Automatic promotion of generated Q&A or raw source code into training data.
* Coverage claims for every One Bangkok repository or external integration.
  The POC includes only the repositories explicitly selected in
  `config/repos.json`.

## Success Criteria

| ID | Success Criterion | Target | Priority |
|---|---|---|---|
| SC-01 | Build deterministic source artifacts without exposing secrets | Digest, security report, and graph contexts complete | Must Have |
| SC-02 | Produce validated training data | Zero dataset validation errors; source citations retained | Must Have |
| SC-03 | Train and fuse both local models sequentially | Qwen and Llama fused artifacts produced | Must Have |
| SC-04 | Preserve One Bangkok scope in direct feature questions | No generic tourism/hotel interpretation for Visitor Pass | Must Have |
| SC-05 | Route repository classification correctly without RAG | All held-out routing cases pass | Optional |
| SC-06 | Answer exact current source questions with RAG/graph context | Answer distinguishes proven code facts from unknown runtime outcomes | Must Have |

## POC Approach

### Proposed Concept

```text
Configured local repositories
  -> deterministic digest (chunks, hashes, metadata, secret exclusions)
  -> Graphify graph + graph-enriched chunks
  -> reviewed source-backed SFT + direct scope/evidence guardrails
  -> MLX LoRA adapter
  -> fused local model

Runtime
  Question -> deterministic feature/router -> obk-rag + graph expansion
           -> grounded prompt -> local fused model -> cited answer
```

Fine-tuning is not used as a code database. It is used to teach answer
discipline and vocabulary. Exact code paths, repository ownership, events,
tables, runtime logs, and behavior that changes with a release must come from
retrieved source context.

### Abdul Maker, Graphify, and one-bangkok-rag integration

Abdul Maker is the workspace shell that coordinates `graphify update .` and
`obk-rag update`. Graphify writes the static code graph to
`one-bangkok-graph/graph.json`. `obk-rag` indexes source chunks into its private
`index.db`, combines FTS5 and local embedding search, and links hits to Graphify
nodes for expansion. The index is distributed through private MinIO with a
SHA-256 manifest; it is not committed to Git.

The model receives retrieved chunks at answer time. It should never treat an
index hit, Graphify edge, Kafka publication, or provider call as proof of a
completed runtime result without direct evidence.

### Test Environment

| Item | Details |
|---|---|
| Application / System | `one-bangkok-llm-digests` |
| Environment | Local macOS Apple Silicon / MLX |
| Model A | `mlx-community/Qwen3-1.7B-4bit-AWQ` |
| Model B | `mlx-community/Llama-3.2-1B-Instruct-4bit` |
| Training method | LoRA; sequential execution only |
| Canonical data | `data/sft_data.jsonl` |
| Retrieval evidence | `data/digest/chunks.jsonl`, `data/graph-chunks.jsonl`, `obk-rag` |

### Test Scenarios

| Test ID | Scenario | Expected Result |
|---|---|---|
| TC-01 | Validate configured repositories and produce a digest | Sources/chunks reported; secret values excluded |
| TC-02 | Prepare canonical SFT into MLX training/validation data | Valid Chat JSONL and deterministic split |
| TC-03 | Train and fuse Qwen3 1.7B | Fused artifact and matching build fingerprint |
| TC-04 | Train and fuse Llama 3.2 1B | Fused artifact and matching build fingerprint |
| TC-05 | Ask Visitor Pass repository-routing question without RAG | `mobile-app, bms, notification` is returned |
| TC-06 | Ask a current flow question using RAG/graph context | Answer cites retrieved source and declares gaps |

## Results and Evidence

### Test Results

| Test ID | Actual Result | Status | Evidence |
|---|---|---|---|
| TC-01 | Digest indexed 3,271 sources and 6,264 chunks; graph produced 3,865 contexts | Pass | EV-01 |
| TC-02 | 1,428 canonical records, 2,484 Chat records, 2,384 train / 100 validation records; validator reported zero errors and warnings | Pass | EV-02 |
| TC-03 | Qwen LoRA and fused model exist with a matching build fingerprint | Pass | EV-03 |
| TC-04 | Llama LoRA and fused model exist with a matching build fingerprint | Pass | EV-04 |
| TC-05 | Qwen returned invented repositories; Llama did not return the requested repository list | Fail | EV-05 |
| TC-06 | Runtime command and source-grounded prompt path are implemented; quality must be accepted only after source-cited review | Partially Met | EV-06 |

### Observed model-only answer failures

The following direct test was intentionally run **without RAG** to measure
whether fine-tuning alone could perform repository routing:

```text
Question: A Visitor Pass defect spans invite creation and visitor email.
Expected: Primary: mobile-app, bms, notification
```

| Model | Actual response pattern | Interpretation |
|---|---|---|
| Qwen3 1.7B fused | Returned unrelated `owncloud` repository URLs | Severe hallucination; the names are not configured One Bangkok repositories and do not answer the task |
| Llama 3.2 1B fused | Generated generic defect description, reproduction steps, and test cases | Failed instruction following; it did not provide the requested primary repository list |

These failures are more important than successful train loss or a generated
adapter file. They show that the models must not be deployed as standalone
routers or factual knowledge bases.

#### Reproducible manual test examples

Both models received the same deterministic prompt:

```text
A Visitor Pass defect spans invite creation and visitor email.
Which repositories contain the primary evidence?
Use exactly this format: Primary: <repositories>.
```

The expected answer is:

```text
Primary: mobile-app, bms, notification
```

**Qwen3 1.7B fused — actual excerpt**

```text
Primary: https://github.com/owncloud/oc-client-web,
https://github.com/owncloud/oc-server, ...
```

This fails because none of the listed `owncloud` repositories are configured
One Bangkok repositories. It is a hallucination, even though the response
starts with the requested `Primary:` label.

**Llama 3.2 1B fused — actual excerpt**

```text
## Defect Description

A Visitor Pass defect spans invite creation and visitor email. The primary
evidence for this defect is `visitor_email`, `inviter_email`, and `pass_email`.
```

This fails because it does not provide repository labels and instead invents a
generic defect description and identifiers. It also ignores the exact output
format requested by the test.

Commands used for equivalent tests:

```bash
TASK_SYSTEM_PROMPT="$(tr '\n' ' ' < config/go-to-chaorai-system.txt)"

uv run --offline --with 'mlx-lm[train]' mlx_lm.generate \
  --model models/go-to-chaorai-qwen3-1.7b-quality-v10-fused \
  --system-prompt "$TASK_SYSTEM_PROMPT" \
  --chat-template-config '{"enable_thinking": false}' \
  --max-tokens 180 --temp 0 \
  --prompt "A Visitor Pass defect spans invite creation and visitor email. Which repositories contain the primary evidence? Use exactly this format: Primary: <repositories>."

# Replace the --model value to test Llama.
```

### Success-Criteria Results

| Criterion ID | Result | Notes |
|---|---|---|
| SC-01 | Met | Deterministic scanner excludes sensitive paths/content and reports paths/reasons only. |
| SC-02 | Met | `data/source-sync-report-v10.json` records 0 errors and 0 warnings. |
| SC-03 | Met | Both adapters and fused artifacts have manifests. |
| SC-04 | Not Met | Both models still generated generic or invented answers in manual tests. |
| SC-05 | Not Met | Historical held-out Qwen score: 1/12; Llama score: 4/12 under an earlier, too-permissive evaluator. |
| SC-06 | Partially Met | RAG/graph retrieval is implemented, but a small model still needs a deterministic router and source-answer review. |

### Evidence

| Evidence ID | Type | Description | Link or Attachment |
|---|---|---|---|
| EV-01 | Manifest | Current digest and graph counts | [`source-sync-report-v10.json`](../data/source-sync-report-v10.json) |
| EV-02 | Validation report | Dataset hash, record counts, source-citation coverage, and validation outcome | [`source-sync-report-v10.json`](../data/source-sync-report-v10.json) |
| EV-03 | Build manifest | Qwen3 1.7B LoRA/fused training fingerprint | [`Qwen fused manifest`](../models/go-to-chaorai-qwen3-1.7b-quality-v10-fused/build-manifest.json) |
| EV-04 | Build manifest | Llama 3.2 1B LoRA/fused training fingerprint | [`Llama fused manifest`](../models/go-to-chaorai-llama-3.2-1b-quality-v10-fused/build-manifest.json) |
| EV-05 | Evaluation output | Held-out classification results and model answers | [`Qwen results`](../data/go-to-chaorai-qwen3-v10-classification-results.json), [`Llama results`](../data/go-to-chaorai-llama-v10-classification-results.json) |
| EV-06 | Runtime implementation | Local retrieval and grounded MLX invocation | [`rag.py`](../src/obk_llm_digests/rag.py) |

## Conclusion and Recommendation

### Key Findings

* The source-to-training pipeline is reproducible and validates the reviewed
  dataset successfully.
* Both small models can be trained and fused locally with modest memory use.
* Model-only repository routing and factual recall are unreliable. Qwen
  hallucinated unrelated repository names; Llama also failed to follow the
  requested output format.
* Fine-tuning gives useful answer-style and domain-prior improvements, but it
  cannot replace retrieval for a multi-repository system that changes often.

### Overall Result

**Result:** Conditionally Successful

**Conclusion:** The POC proves that the local training and artifact pipeline is
workable. It does not prove that 1B–1.7B fine-tuned models can safely be used
as standalone authorities for One Bangkok repository routing or current code
facts.

### Recommendation

**Recommended option:** Proceed with conditions

**Rationale:** Use the fused model only behind deterministic routing plus RAG
and graph context. Treat retrieved source as the authority. Do not deploy a
model-only assistant for code facts or cross-service ownership until it passes
a stricter held-out evaluation.

### Path to achieve an internal pilot

1. **Deterministic first step:** Map feature keywords to the configured
   repositories. This avoids asking a small generative model to remember
   repository ownership.
2. **Retrieve before generate:** Use `obk-rag` hybrid search and `--expand` to
   attach current graph-related source chunks. Require the answer to cite them.
3. **Deepen reviewed data:** Expand each selected feature across explain,
   debug, analyse, classify, and evidence-gap tasks. Every record needs a
   source citation and must state what is unproven where relevant.
4. **Separate task evaluation:** Keep repository routing, TRUE/FALSE evidence
   checks, business-flow explanations, and technical debugging as separate
   held-out test sets. Do not train on evaluation prompts.
5. **Evaluate a larger candidate:** Test a current 3B–4B 4-bit instruct model.
   It may follow instructions better than 1B–1.7B, but it still requires the
   same RAG and evidence controls. Consider 7B only after measuring local
   memory, latency, and LoRA training feasibility.
6. **Promote by evidence:** Require a model manifest, RAG index manifest,
   prompt version, strict evaluation output, and feature-owner approval before
   giving the model to a wider internal audience.

## Next Steps

| Action | Owner | Target Date | Status |
|---|---|---|---|
| Re-run strict evaluator after the latest data rebuild | Internal AI team | TBD | Pending |
| Add deterministic feature/repository routing before generation | Internal AI team | TBD | Pending |
| Run source-grounded Visitor Pass, Booking, IAM, Workplace, and Notification acceptance cases | Feature owners | TBD | Pending |
| Evaluate a stronger 3B–4B 4-bit candidate if hardware budget permits | Internal AI team | TBD | Pending |
| Record a follow-up ADR before internal release | Technical owner | TBD | Pending |

## Additional Information

### Architecture or Process Flow

The fine-tune is responsible for: scope, terminology, concise explanations,
and evidence-boundary behavior. The router is responsible for selecting
repositories/features. RAG and Graphify are responsible for fetching current
code and related symbols. The user-facing answer must distinguish a static
relationship from a completed runtime transaction.

### Assumptions and Constraints

* Local repositories are already cloned and readable by the configured paths.
* Only reviewed source-backed Q&A is added to canonical SFT.
* Base-model knowledge can conflict with One Bangkok terms, particularly
  generic terms such as Visitor Pass.
* Training runs sequentially; two MLX trainers must not run at the same time.

### Risks and Limitations

| Risk or Limitation | Impact | Mitigation |
|---|---|---|
| Small-model hallucination | Incorrect repository, feature, or flow claims | Deterministic router, RAG context, strict evaluation, source citations |
| Stale fine-tune knowledge | Incorrect answer after code changes | Refresh digest/RAG/graph; train only stable reviewed knowledge |
| Generated Q&A used without review | Hallucinations become training data | Keep generated drafts separate; require review before SFT promotion |
| Context retrieval misses source | Model fills gaps from generic priors | Return an evidence-gap response; broaden/repair retrieval rather than guess |

### Technical Details

Prepare data without retraining:

```bash
./scripts/build_all_local_models.sh --prepare-only --skip-source-sync
```

Train/fuse both models sequentially using current source artifacts:

```bash
./scripts/build_all_local_models.sh --skip-source-sync
```

Run the strict held-out classification evaluation:

```bash
PYTHONPATH=src uv run --offline --with 'mlx-lm[train]' \
  python scripts/evaluate_domain_model.py \
  --model models/go-to-chaorai-qwen3-1.7b-quality-v10-fused \
  --eval data/go-to-chaorai-v10-classification-eval.jsonl \
  --output data/go-to-chaorai-qwen3-v10-classification-results.json \
  --max-tokens 180
```

Use RAG for a current source question:

```bash
PYTHONPATH=src uv run --offline --with mlx-lm --with-editable . \
  obk-llm-digests ask-rag \
  --obk-rag-project /path/to/one-bangkok-workspace/obk-rag \
  --model models/go-to-chaorai-qwen3-1.7b-quality-v10-fused \
  --question "Explain the Visitor Pass flow." \
  --limit 8 --max-context-chars 28000 --max-tokens 900 --temp 0.1
```

## Links

* [Project repository](https://github.com/mtel-thailand/ob-llm-fine-tune)
* [Fine-tuning guide](LOCAL_ONE_BANGKOK_AI_ASSISTANT_FINE_TUNING.md)
* [Training pipeline](../scripts/build_all_local_models.sh)
* [Qwen configuration](../config/mlx-qwen3-1.7b-quality-v10.yaml)
* [Llama configuration](../config/mlx-llama3.2-1b-quality-v10.yaml)
* [Abdul Maker workspace](../../../abdul-maker/README.md)
* [one-bangkok-rag](../../../obk-rag/README.md)
