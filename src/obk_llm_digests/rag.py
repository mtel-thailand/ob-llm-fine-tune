"""Small, local, source-grounded retrieval for MLX inference.

This deliberately uses the standard library.  Fine-tuned weights teach the
assistant how to answer; this module supplies the current code evidence that
must constrain each answer.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "at", "be", "do", "does", "for", "from", "how",
    "i", "in", "is", "it", "of", "on", "or", "the", "this", "to", "what", "with",
    "answer", "clearly", "context", "explain", "flow", "prove", "retrieved", "source", "through",
})


def _tokens(value: str) -> list[str]:
    expanded = re.sub(r"([a-z])([A-Z])", r"\1 \2", value).lower()
    return [word for word in re.findall(r"[a-z0-9_]{2,}", expanded) if word not in _STOP_WORDS]


@dataclass(frozen=True)
class RetrievedChunk:
    repository: str
    path: str
    line_start: int
    line_end: int
    text: str
    graph_summary: str = ""

    @property
    def reference(self) -> str:
        return f"{self.repository}/{self.path}:{self.line_start}-{self.line_end}"


def _records(path: str | Path):
    """Yield a normalised view of digest chunks or graph-chunk packages."""
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record.get("source_chunks"), list):
                labels = ", ".join(str(node.get("label", "")) for node in record.get("graph_nodes", [])[:12])
                for chunk in record["source_chunks"]:
                    if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                        yield RetrievedChunk(
                            repository=str(chunk.get("repository", "unknown")), path=str(chunk.get("path", "unknown")),
                            line_start=int(chunk.get("line_start", 1)), line_end=int(chunk.get("line_end", 1)),
                            text=chunk["text"], graph_summary=labels,
                        )
            elif isinstance(record.get("text"), str):
                yield RetrievedChunk(
                    repository=str(record.get("repository", "unknown")), path=str(record.get("path", "unknown")),
                    line_start=int(record.get("line_start", 1)), line_end=int(record.get("line_end", 1)), text=record["text"],
                )


def retrieve(query: str, contexts: str | Path, *, limit: int = 5) -> list[RetrievedChunk]:
    """Rank source chunks with deterministic lexical matching, no external API."""
    terms = _tokens(query)
    if not terms:
        raise ValueError("question must contain searchable terms")
    candidates: list[RetrievedChunk] = []
    seen: set[tuple[str, str, int]] = set()
    for chunk in _records(contexts):
        identity = (chunk.repository, chunk.path, chunk.line_start)
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(chunk)
    if not candidates:
        return []
    # In a codebase, `app` or `service` occur in thousands of chunks while a
    # pair such as `visitor pass` is discriminating.  IDF prevents broad words
    # from drowning out the actual feature name.
    document_frequency = {term: 0 for term in terms}
    token_cache: list[tuple[RetrievedChunk, set[str], set[str], set[str], list[str]]] = []
    for chunk in candidates:
        path_words = set(_tokens(chunk.path))
        body_sequence = _tokens(chunk.text)
        body_words = set(body_sequence)
        graph_words = set(_tokens(chunk.graph_summary))
        token_cache.append((chunk, path_words, body_words, graph_words, body_sequence))
        all_words = path_words | body_words | graph_words
        for term in document_frequency:
            if term in all_words:
                document_frequency[term] += 1
    total = len(candidates)
    weight = {term: 1.0 + math.log((total + 1) / (count + 1)) for term, count in document_frequency.items()}
    query_bigrams = set(zip(terms, terms[1:]))
    ranked: list[tuple[float, RetrievedChunk]] = []
    for chunk, path_words, body_words, graph_words, body_sequence in token_cache:
        score = sum(8 * weight[term] for term in terms if term in path_words)
        score += sum(2 * weight[term] for term in terms if term in graph_words)
        score += sum(weight[term] for term in terms if term in body_words)
        body_bigrams = set(zip(body_sequence, body_sequence[1:]))
        score += sum(12 * (weight[left] + weight[right]) for left, right in query_bigrams if (left, right) in body_bigrams)
        if score:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: (-item[0], item[1].repository, item[1].path, item[1].line_start))
    return [chunk for _, chunk in ranked[:limit]]


def retrieve_obk_rag(query: str, project: str | Path, *, limit: int = 5) -> list[RetrievedChunk]:
    """Query the production obk-rag hybrid index and retain its source text.

    obk-rag owns FTS/vector retrieval and graph expansion.  This adapter only
    converts its documented JSON response into the common prompt format.
    """
    result = subprocess.run(
        ["uv", "run", "--project", str(project), "obk-rag", "search", query,
         "--expand", "--json", "--limit", str(limit)],
        text=True, capture_output=True, check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise ValueError(f"obk-rag search failed: {detail}")
    try:
        hits = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("obk-rag did not return JSON search results") from error
    if not isinstance(hits, list):
        raise ValueError("obk-rag returned an unexpected JSON search result")
    chunks: list[RetrievedChunk] = []
    for hit in hits:
        if not isinstance(hit, dict) or not isinstance(hit.get("content"), str):
            continue
        neighbors = hit.get("neighbors", [])
        graph_summary = "; ".join(
            f"{edge.get('relation', 'related')}: {edge.get('label', '')}"
            for edge in neighbors[:12] if isinstance(edge, dict)
        )
        chunks.append(RetrievedChunk(
            repository=str(hit.get("repo", "unknown")), path=str(hit.get("path", "unknown")),
            line_start=int(hit.get("start_line", 1)), line_end=int(hit.get("end_line", 1)),
            text=hit["content"], graph_summary=graph_summary,
        ))
    return chunks


def build_prompt(question: str, chunks: list[RetrievedChunk], *, max_context_chars: int = 12000) -> str:
    if not chunks:
        return (
            "You are Go-To-ChaoRai, an internal engineering assistant. No source context was retrieved for this "
            "question. Say exactly that more source context is required; do not answer from general knowledge.\n\n"
            f"Question: {question}"
        )
    remaining = max_context_chars
    sections: list[str] = []
    for chunk in chunks:
        header = f"[SOURCE {chunk.reference}]\n"
        available = max(0, remaining - len(header) - 1)
        if not available:
            break
        body = chunk.text[:available]
        sections.append(header + body)
        remaining -= len(header) + len(body) + 1
    context = "\n\n".join(sections)
    return f"""You are Go-To-ChaoRai, an internal One Bangkok engineering assistant.
Answer ONLY about the One Bangkok codebase from the retrieved source excerpts below. Do not use generic industry knowledge to fill a gap.
If the question is not about One Bangkok, say that Go-To-ChaoRai only supports One Bangkok engineering and product questions.
If the excerpts do not prove a requested fact, say: \"The retrieved source does not establish this; more source context is required.\"
Do not claim an API call, database table, Kafka event, external-system result, QR generation, email delivery, or physical-access result unless the excerpt explicitly shows it.
Give a direct, clear answer in English. Cite every concrete claim using the supplied SOURCE reference.

Retrieved source excerpts:
{context}

Question: {question}
"""


def ask_mlx(question: str, chunks: list[RetrievedChunk], model: str | Path, *,
            max_context_chars: int = 12000, max_tokens: int = 900, temperature: float = 0.1) -> int:
    prompt = build_prompt(question, chunks, max_context_chars=max_context_chars)
    command = [
        "mlx_lm.generate", "--model", str(model), "--prompt", prompt,
        "--chat-template-config", '{"enable_thinking": false}', "--max-tokens", str(max_tokens),
        "--temp", str(temperature), "--verbose", "false",
    ]
    print("Retrieved source context:")
    for chunk in chunks:
        print(f"- {chunk.reference}")
    print("\nAnswer:\n", flush=True)
    return subprocess.run(command, check=False).returncode
