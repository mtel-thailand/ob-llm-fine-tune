from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from obk_llm_digests.config import Settings
from obk_llm_digests.digest import build, build_sft, validate_output
from obk_llm_digests.review import review_report
from obk_llm_digests import drafts
from obk_llm_digests.features import load_features
from obk_llm_digests.sft_data import load_sft_records
from obk_llm_digests.graph_context import build_graph_chunks, build_graph_contexts


class PipelineTests(unittest.TestCase):
    def make_settings(self, root: Path, **extra: object) -> Settings:
        config = {"chunk_lines": 2, "chunk_overlap_lines": 1, "repositories": [
            {"label": "next", "path": str(root / "next"), "framework": "nextjs"},
            {"label": "api", "path": str(root / "api"), "framework": "dotnet", "include": ["src/**"]},
        ], **extra}
        config_path = root / "repos.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return Settings.from_file(config_path)

    def test_digest_filters_secrets_binary_and_excludes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "next" / "src").mkdir(parents=True)
            (root / "api" / "src").mkdir(parents=True)
            (root / "api" / "build").mkdir(parents=True)
            (root / "next" / "packages" / "ui" / "node_modules" / "dependency").mkdir(parents=True)
            (root / "next" / "src" / "generated").mkdir(parents=True)
            (root / "next" / "src" / "page.tsx").write_text("one\ntwo\nthree\n", encoding="utf-8")
            (root / "next" / "packages" / "ui" / "node_modules" / "dependency" / "index.ts").write_text("ignored", encoding="utf-8")
            (root / "next" / "src" / "generated" / "client.ts").write_text("ignored", encoding="utf-8")
            (root / "next" / ".env").write_text("SECRET=x", encoding="utf-8")
            (root / "next" / "src" / "key.ts").write_text('const token = "abcdefghijk"', encoding="utf-8")
            (root / "next" / "src" / "blob.dat").write_bytes(b"\0binary")
            (root / "api" / "src" / "Program.cs").write_text("class Program {}", encoding="utf-8")
            (root / "api" / "build" / "ignored.cs").write_text("ignored", encoding="utf-8")
            output = root / "out"
            manifest = build(self.make_settings(root, allow_unknown_text=True), output)
            self.assertEqual(manifest["sources"], 2)
            self.assertGreater(manifest["chunks"], 2)
            report = json.loads((output / "security-report.json").read_text())
            self.assertEqual({entry["reason"] for entry in report}, {"sensitive filename", "possible secret in content", "binary or non-UTF-8 file"})
            self.assertNotIn("abcdefghijk", (output / "digest.md").read_text())
            validate_output(output)

    def test_second_digest_reuses_unchanged_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "next").mkdir()
            (root / "api" / "src").mkdir(parents=True)
            (root / "next" / "index.ts").write_text("export const a = 1", encoding="utf-8")
            (root / "api" / "src" / "Program.cs").write_text("class Program {}", encoding="utf-8")
            settings, output = self.make_settings(root), root / "out"
            build(settings, output)
            self.assertEqual(build(settings, output)["reused_files"], 2)

    def test_build_sft_requires_complete_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reviewed = root / "reviewed.jsonl"
            reviewed.write_text(json.dumps({"review_status": "approved", "reviewer": "QA", "reviewed_at": "2026-09-23T00:00:00Z", "messages": [{"role": "user", "content": "x"}]}) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_sft(reviewed, root / "sft.jsonl")
            reviewed.write_text(json.dumps({"review_status": "needs_human_review", "messages": [
                {"role": "system", "content": "Ground answers."}, {"role": "user", "content": "What does this do?"},
                {"role": "assistant", "content": "It handles a request."}]}) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_sft(reviewed, root / "sft.jsonl")
            reviewed.write_text(json.dumps({"review_status": "approved", "reviewer": "QA", "reviewed_at": "2026-09-23T00:00:00Z", "messages": [
                {"role": "system", "content": "Ground answers."}, {"role": "user", "content": "What does this do?"},
                {"role": "assistant", "content": "It handles a request."}]}) + "\n", encoding="utf-8")
            self.assertEqual(build_sft(reviewed, root / "sft.jsonl"), 1)

    def test_sft_loader_requires_assistant_as_last_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dataset = Path(temporary) / "sft.jsonl"
            dataset.write_text(json.dumps({"messages": [
                {"role": "system", "content": "Use sources."}, {"role": "assistant", "content": "Answer."},
                {"role": "user", "content": "Question"}]}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "final message"):
                load_sft_records(dataset)

    def test_review_report_checks_evidence_and_approval_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            digest = root / "digest"
            digest.mkdir()
            chunk = {"repository": "api", "path": "src/app.ts", "source_sha256": "a" * 64}
            (digest / "chunks.jsonl").write_text(json.dumps(chunk) + "\n", encoding="utf-8")
            reviewed = root / "reviewed.jsonl"
            record = {"review_status": "approved", "source": {**chunk, "lines": "1-2"}, "messages": [
                {"role": "system", "content": "Use evidence."}, {"role": "user", "content": "What is this?"},
                {"role": "assistant", "content": "It is src/app.ts:1-2."}], "reviewer": "dev@example.com", "reviewed_at": "2026-09-23T00:00:00Z"}
            reviewed.write_text(json.dumps(record) + "\n", encoding="utf-8")
            report, valid = review_report(reviewed, digest)
            self.assertTrue(valid)
            self.assertFalse(report["errors"])

    def test_generate_drafts_marks_records_for_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            digest = root / "digest"
            digest.mkdir()
            chunk = {"repository": "api", "path": "src/app.ts", "source_sha256": "a" * 64,
                     "line_start": 1, "line_end": 5, "text": "export function health() {\n  return { status: 'ok', version: '1', service: 'booking' };\n}\n\nexport const healthy = true;"}
            (digest / "chunks.jsonl").write_text(json.dumps(chunk) + "\n", encoding="utf-8")
            original = drafts.request_completion
            drafts.request_completion = lambda *_: {"question": "What does health return?", "answer": "It returns status and version. Source: api/src/app.ts:1-3."}
            try:
                created, failures = drafts.generate_drafts(digest, root / "drafts.jsonl", provider="ollama", base_url="x", model="tiny", limit=1)
            finally:
                drafts.request_completion = original
            self.assertEqual((created, failures), (1, []))
            record = json.loads((root / "drafts.jsonl").read_text())
            self.assertEqual(record["review_status"], "needs_human_review")
            original = drafts.request_completion
            drafts.request_completion = lambda *_: {"question": "Duplicate?", "answer": "No new source should be used."}
            try:
                created, _ = drafts.generate_drafts(digest, root / "drafts.jsonl", provider="ollama", base_url="x", model="tiny", limit=1, append=True)
            finally:
                drafts.request_completion = original
            self.assertEqual(created, 0)

    def test_graph_context_maps_nodes_to_source_and_neighbors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            digest = root / "digest"
            digest.mkdir()
            chunks = [
                {"repository": "mobile", "path": "app/screen.ts", "source_sha256": "a" * 64, "line_start": 1, "line_end": 2, "text": "call api"},
                {"repository": "api", "path": "src/controller.ts", "source_sha256": "b" * 64, "line_start": 1, "line_end": 2, "text": "handle request"},
            ]
            (digest / "chunks.jsonl").write_text("".join(json.dumps(chunk) + "\n" for chunk in chunks), encoding="utf-8")
            graph = {"nodes": [{"id": "screen", "label": "Screen", "source_file": "one-bangkok-app/app/screen.ts", "source_location": "L1"},
                                {"id": "controller", "label": "Controller", "source_file": "obk-api/src/controller.ts", "source_location": "L1"}],
                     "links": [{"source": "screen", "target": "controller", "relation": "calls"}]}
            graph_path, output = root / "graph.json", root / "contexts.jsonl"
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            self.assertEqual(build_graph_contexts(graph_path, digest, output, hops=1, limit=2), 2)
            context = json.loads(output.read_text().splitlines()[0])
            self.assertEqual(len(context["source_chunks"]), 2)
            self.assertEqual(context["graph_edges"][0]["relation"], "calls")
            enriched = root / "graph-chunks.jsonl"
            self.assertEqual(build_graph_chunks(graph_path, digest, enriched, hops=1, limit=2), 2)
            chunk = json.loads(enriched.read_text().splitlines()[0])
            self.assertTrue(chunk["primary_nodes"])
            self.assertTrue(chunk["source_chunks"][0]["graph_node_ids"])
            balanced = root / "balanced.jsonl"
            self.assertEqual(build_graph_chunks(graph_path, digest, balanced, hops=1, limit=2, balanced_by_repository=True), 2)
            self.assertEqual({json.loads(line)["source"]["repository"] for line in balanced.read_text().splitlines()}, {"api", "mobile"})

    def test_generate_graph_drafts_requires_context_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "run graph-context first"):
                drafts.generate_graph_drafts(root / "missing.jsonl", root / "out.jsonl", provider="ollama", base_url="x", model="tiny", limit=1)

    def test_feature_drafts_use_only_matching_graph_context_and_mark_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            features_path = root / "features.json"
            features_path.write_text(json.dumps({"features": [{"id": "visitor-pass", "title": "Visitor Pass", "keywords": ["visitor", "pass"]}]}), encoding="utf-8")
            context = {"id": "graph-chunk:x", "source": {"repository": "api", "path": "src/visitor.ts", "line_start": 1, "line_end": 4, "source_sha256": "a" * 64},
                       "primary_node": {"id": "visitor"}, "primary_nodes": [{"id": "visitor"}], "graph_nodes": [{"id": "visitor"}], "graph_edges": [],
                       "source_chunks": [{"repository": "api", "path": "src/visitor.ts", "line_start": 1, "line_end": 4, "source_sha256": "a" * 64, "text": "export function createVisitorPass() { return 'pass'; }"}]}
            contexts = root / "contexts.jsonl"
            contexts.write_text(json.dumps(context) + "\n", encoding="utf-8")
            original = drafts.request_completion
            drafts.request_completion = lambda *_: {"question": "How is a visitor pass created?", "answer": "It calls createVisitorPass. Source: api/src/visitor.ts:1-4."}
            try:
                created, failures = drafts.generate_feature_drafts(contexts, root / "drafts.jsonl", features=load_features(features_path), provider="ollama", base_url="x", model="tiny", limit_per_feature=1)
            finally:
                drafts.request_completion = original
            self.assertEqual((created, failures), (1, []))
            record = json.loads((root / "drafts.jsonl").read_text())
            self.assertEqual(record["feature"]["id"], "visitor-pass")
            self.assertEqual(record["review_status"], "needs_human_review")

    def test_feature_drafts_without_selection_uses_every_configured_feature(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            features_path = root / "features.json"
            features_path.write_text(json.dumps({"features": [
                {"id": "visitor-pass", "title": "Visitor Pass", "keywords": ["visitor"]},
                {"id": "notification", "title": "Notification", "keywords": ["notification"]},
            ]}), encoding="utf-8")
            context = {"source": {"repository": "api", "path": "src/visitor-notification.ts", "line_start": 1, "line_end": 2, "source_sha256": "a" * 64},
                       "graph_edges": [], "source_chunks": [{"repository": "api", "path": "src/visitor-notification.ts", "line_start": 1, "line_end": 2, "source_sha256": "a" * 64, "text": "send notification to visitor"}]}
            contexts = root / "contexts.jsonl"
            contexts.write_text(json.dumps(context) + "\n", encoding="utf-8")
            original = drafts.request_completion
            drafts.request_completion = lambda *_: {"question": "Q?", "answer": "A. Source: api/src/visitor-notification.ts:1-2."}
            try:
                created, failures = drafts.generate_feature_drafts(contexts, root / "drafts.jsonl", features=load_features(features_path), provider="ollama", base_url="x", model="tiny", limit_per_feature=1)
            finally:
                drafts.request_completion = original
            self.assertEqual((created, failures), (2, []))

    def test_feature_drafts_stop_after_three_consecutive_model_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            features_path = root / "features.json"
            features_path.write_text(json.dumps({"features": [{"id": "auth", "title": "Auth", "keywords": ["auth"]}]}), encoding="utf-8")
            source = {"repository": "api", "path": "src/auth.ts", "line_start": 1, "line_end": 2, "source_sha256": "a" * 64}
            context = {"source": source, "graph_edges": [], "source_chunks": [{**source, "text": "auth auth auth"}]}
            contexts = root / "contexts.jsonl"
            contexts.write_text("".join(json.dumps(context) + "\n" for _ in range(4)), encoding="utf-8")
            original = drafts.request_completion
            drafts.request_completion = lambda *_: (_ for _ in ()).throw(OSError("authentication failed"))
            try:
                with self.assertRaisesRegex(ValueError, "3 consecutive"):
                    drafts.generate_feature_drafts(contexts, root / "drafts.jsonl", features=load_features(features_path), provider="ollama", base_url="x", model="tiny", limit_per_feature=1)
            finally:
                drafts.request_completion = original


if __name__ == "__main__":
    unittest.main()
