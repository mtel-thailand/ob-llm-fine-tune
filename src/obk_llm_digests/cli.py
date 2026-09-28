from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Settings
from .digest import build, build_sft, validate_output
from .review import write_review_report
from .drafts import generate_drafts, generate_feature_drafts, generate_graph_drafts
from .features import load_features
from .graph_context import build_graph_chunks, build_graph_contexts
from .rag import ask_mlx, build_prompt, retrieve, retrieve_obk_rag


def _settings(location: str) -> Settings:
    settings = Settings.from_file(location)
    missing = [str(repo.path) for repo in settings.repositories if not repo.path.is_dir()]
    if missing:
        raise ValueError("repository paths not found: " + ", ".join(missing))
    return settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Build review-first LLM fine-tuning digests from local repositories")
    commands = parser.add_subparsers(dest="command", required=True)
    digest = commands.add_parser("digest")
    digest.add_argument("--config", required=True)
    digest.add_argument("--output", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--config", required=True)
    validate.add_argument("--output")
    review = commands.add_parser("review")
    review.add_argument("--reviewed", required=True)
    review.add_argument("--digest", required=True)
    review.add_argument("--report", required=True)
    generate = commands.add_parser("generate-drafts")
    generate.add_argument("--digest", required=True)
    generate.add_argument("--output", required=True)
    generate.add_argument("--model", required=True)
    generate.add_argument("--provider", choices=("ollama", "openai", "openai-responses"), default="ollama")
    generate.add_argument("--base-url", default="http://127.0.0.1:11434")
    generate.add_argument("--limit", type=int, default=25)
    generate.add_argument("--repository")
    generate.add_argument("--existing")
    generate.add_argument("--append", action="store_true")
    graph_context = commands.add_parser("graph-context")
    graph_context.add_argument("--graph", required=True)
    graph_context.add_argument("--digest", required=True)
    graph_context.add_argument("--output", required=True)
    graph_context.add_argument("--hops", type=int, choices=(1, 2), default=1)
    graph_context.add_argument("--limit", type=int, default=100)
    graph_context.add_argument("--relation", action="append", default=[])
    graph_context.add_argument("--max-source-chunks", type=int, default=6)
    graph_chunks = commands.add_parser("graph-chunks")
    graph_chunks.add_argument("--graph", required=True)
    graph_chunks.add_argument("--digest", required=True)
    graph_chunks.add_argument("--output", required=True)
    graph_chunks.add_argument("--hops", type=int, choices=(1, 2), default=1)
    graph_chunks.add_argument("--limit", type=int, default=100)
    graph_chunks.add_argument("--relation", action="append", default=[])
    graph_chunks.add_argument("--max-related-chunks", type=int, default=6)
    graph_chunks.add_argument("--balanced-by-repository", action="store_true",
                              help="Round-robin repositories before applying --limit")
    graph_drafts = commands.add_parser("generate-graph-drafts")
    graph_drafts.add_argument("--contexts", required=True)
    graph_drafts.add_argument("--output", required=True)
    graph_drafts.add_argument("--model", required=True)
    graph_drafts.add_argument("--provider", choices=("ollama", "openai", "openai-responses"), default="ollama")
    graph_drafts.add_argument("--base-url", default="http://127.0.0.1:11434")
    graph_drafts.add_argument("--limit", type=int, default=25)
    graph_drafts.add_argument("--append", action="store_true")
    feature_drafts = commands.add_parser("generate-feature-drafts")
    feature_drafts.add_argument("--contexts", required=True)
    feature_drafts.add_argument("--features", required=True)
    feature_drafts.add_argument("--output", required=True)
    feature_drafts.add_argument("--model", required=True)
    feature_drafts.add_argument("--provider", choices=("ollama", "openai", "openai-responses"), default="ollama")
    feature_drafts.add_argument("--base-url", default="http://127.0.0.1:11434")
    feature_selection = feature_drafts.add_mutually_exclusive_group()
    feature_selection.add_argument("--feature", action="append", default=[],
                                   help="Generate only this configured feature; repeat to select several")
    feature_selection.add_argument("--all-features-from-config", action="store_true",
                                   help="Explicitly generate every feature in --features")
    feature_drafts.add_argument("--limit-per-feature", type=int, default=25)
    feature_drafts.add_argument("--append", action="store_true")
    list_features = commands.add_parser("list-features")
    list_features.add_argument("--features", required=True)
    sft = commands.add_parser("build-sft")
    sft.add_argument("--reviewed", required=True)
    sft.add_argument("--output", required=True)
    rag_prompt = commands.add_parser("rag-prompt", help="retrieve local source context and print a grounded prompt")
    rag_prompt.add_argument("--contexts", required=True, help="graph-chunks.jsonl or digest chunks.jsonl")
    rag_prompt.add_argument("--question", required=True)
    rag_prompt.add_argument("--limit", type=int, default=5)
    rag_prompt.add_argument("--max-context-chars", type=int, default=12000)
    ask_rag = commands.add_parser("ask-rag", help="retrieve local source context then run an installed MLX model")
    ask_source = ask_rag.add_mutually_exclusive_group(required=True)
    ask_source.add_argument("--contexts", help="graph-chunks.jsonl or digest chunks.jsonl")
    ask_source.add_argument("--obk-rag-project", help="path to the production obk-rag project")
    ask_rag.add_argument("--question", required=True)
    ask_rag.add_argument("--model", required=True)
    ask_rag.add_argument("--limit", type=int, default=5)
    ask_rag.add_argument("--max-context-chars", type=int, default=12000)
    ask_rag.add_argument("--max-tokens", type=int, default=900)
    ask_rag.add_argument("--temp", type=float, default=0.1)
    args = parser.parse_args()
    try:
        if args.command == "digest":
            manifest = build(_settings(args.config), args.output)
            print(f"digest complete: {manifest['sources']} files, {manifest['chunks']} chunks, {manifest['reused_files']} reused")
        elif args.command == "validate":
            settings = _settings(args.config)
            if args.output:
                validate_output(args.output)
            print(f"config valid: {len(settings.repositories)} repositories")
        elif args.command == "review":
            report, valid = write_review_report(args.reviewed, args.digest, args.report)
            print(f"review report: {report['records']} records, {len(report['errors'])} errors, {len(report['warnings'])} warnings")
            if not valid:
                parser.exit(2, "error: review validation failed; inspect the report\n")
        elif args.command == "generate-drafts":
            created, failures = generate_drafts(args.digest, args.output, provider=args.provider,
                                                base_url=args.base_url, model=args.model, limit=args.limit,
                                                repository=args.repository, existing=args.existing, append=args.append)
            print(f"draft generation complete: {created} drafts, {len(failures)} failures")
            if failures:
                parser.exit(2, "error: some drafts failed; reduce scope or inspect the model endpoint\n")
        elif args.command == "graph-context":
            count = build_graph_contexts(args.graph, args.digest, args.output, hops=args.hops, limit=args.limit,
                                         relations=tuple(args.relation), max_source_chunks=args.max_source_chunks)
            print(f"graph contexts complete: {count} contexts")
        elif args.command == "graph-chunks":
            count = build_graph_chunks(args.graph, args.digest, args.output, hops=args.hops, limit=args.limit,
                                       relations=tuple(args.relation), max_related_chunks=args.max_related_chunks,
                                       balanced_by_repository=args.balanced_by_repository)
            print(f"graph chunks complete: {count} enriched chunks")
        elif args.command == "generate-graph-drafts":
            created, failures = generate_graph_drafts(args.contexts, args.output, provider=args.provider,
                                                      base_url=args.base_url, model=args.model, limit=args.limit,
                                                      append=args.append)
            print(f"graph draft generation complete: {created} drafts, {len(failures)} failures")
            if failures:
                parser.exit(2, "error: some graph drafts failed; inspect the model endpoint\n")
        elif args.command == "generate-feature-drafts":
            created, failures = generate_feature_drafts(
                args.contexts, args.output, features=load_features(args.features), provider=args.provider,
                base_url=args.base_url, model=args.model, limit_per_feature=args.limit_per_feature,
                selected_features=tuple(args.feature), append=args.append,
            )
            print(f"feature draft generation complete: {created} drafts, {len(failures)} failures")
            if failures:
                for failure in failures[:3]:
                    print("failure: " + failure, file=sys.stderr)
                parser.exit(2, "error: some feature drafts failed; inspect the model endpoint\n")
        elif args.command == "list-features":
            for feature in load_features(args.features):
                print(f"{feature.id}\t{feature.title}\t{', '.join(feature.keywords)}")
        elif args.command == "rag-prompt":
            chunks = retrieve(args.question, args.contexts, limit=args.limit)
            print(build_prompt(args.question, chunks, max_context_chars=args.max_context_chars))
        elif args.command == "ask-rag":
            chunks = (retrieve_obk_rag(args.question, args.obk_rag_project, limit=args.limit)
                      if args.obk_rag_project else retrieve(args.question, args.contexts, limit=args.limit))
            exit_code = ask_mlx(args.question, chunks, args.model, max_context_chars=args.max_context_chars,
                                max_tokens=args.max_tokens, temperature=args.temp)
            if exit_code:
                parser.exit(exit_code, f"error: MLX generation failed with exit code {exit_code}\n")
        else:
            print(f"SFT dataset complete: {build_sft(args.reviewed, args.output)} reviewed examples")
    except (OSError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    main()
