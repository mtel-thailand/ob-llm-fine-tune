from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path


def _node_location(node: dict) -> str | None:
    for container in (node, node.get("metadata", {})):
        if not isinstance(container, dict):
            continue
        for key in ("source_file", "file_path", "path", "file", "location", "source_location"):
            value = container.get(key)
            # Graphify stores source_file as the path and source_location as L<line>.
            if isinstance(value, str) and value and not re.fullmatch(r"L\d+", value):
                return re.sub(r":\d+(?::\d+)?$", "", value).replace("\\", "/")
    return None


def _node_line(node: dict) -> int | None:
    for container in (node, node.get("metadata", {})):
        if not isinstance(container, dict):
            continue
        for key in ("source_location", "location"):
            value = container.get(key)
            if isinstance(value, str):
                match = re.search(r"(?:L|:)(\d+)(?::\d+)?$", value)
                if match:
                    return int(match.group(1))
    return None


def _normalise_graph(graph_path: str | Path) -> tuple[dict[str, dict], list[dict]]:
    raw = json.loads(Path(graph_path).read_text(encoding="utf-8"))
    raw_nodes = raw.get("nodes", []) if isinstance(raw, dict) else []
    raw_edges = (raw.get("edges") or raw.get("links") or []) if isinstance(raw, dict) else []
    if isinstance(raw_nodes, dict):
        raw_nodes = [{"id": key, **(value if isinstance(value, dict) else {"label": str(value)})} for key, value in raw_nodes.items()]
    nodes: dict[str, dict] = {}
    for index, node in enumerate(raw_nodes):
        if not isinstance(node, dict):
            continue
        identifier = str(node.get("id", node.get("key", node.get("name", index))))
        nodes[identifier] = {"id": identifier, "label": str(node.get("label", node.get("name", identifier))),
                             "kind": node.get("type", node.get("kind")), "location": _node_location(node),
                             "line": _node_line(node)}
    edges = []
    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        source, target = edge.get("source", edge.get("from")), edge.get("target", edge.get("to"))
        if source is not None and target is not None:
            edges.append({"source": str(source), "target": str(target),
                          "relation": str(edge.get("type", edge.get("relation", edge.get("label", "related_to"))))})
    return nodes, edges


def _map_nodes_to_chunks(nodes: dict[str, dict], digest_dir: str | Path) -> dict[str, list[dict]]:
    """Map locations in a graph to chunks in one streaming pass.

    Graph paths often include an outer repository directory while digest paths do
    not. Indexing every suffix of each graph source path handles both layouts
    without an O(nodes × chunks) comparison or loading the whole digest in RAM.
    """
    suffixes: dict[str, list[str]] = defaultdict(list)
    for node_id, node in nodes.items():
        if not node["location"]:
            continue
        parts = node["location"].lstrip("./").split("/")
        for index in range(len(parts)):
            suffixes["/".join(parts[index:])].append(node_id)
    mapped: dict[str, list[dict]] = defaultdict(list)
    with (Path(digest_dir) / "chunks.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                # Legacy output could contain a path with a control character.
                # The scanner now excludes these paths; skip it until digest is rebuilt.
                continue
            path = chunk["path"].lstrip("./")
            for node_id in suffixes.get(path, []):
                node_line = nodes[node_id].get("line")
                contains_symbol = node_line is not None and chunk["line_start"] <= node_line <= chunk["line_end"]
                # Prefer the chunk that contains the symbol's Graphify line location.
                if not mapped[node_id] or contains_symbol:
                    mapped[node_id].append(chunk)
                    if len(mapped[node_id]) > 1:
                        mapped[node_id] = [chunk]
    return mapped


def _adjacency(edges: list[dict], relations: tuple[str, ...]) -> dict[str, list[tuple[str, dict]]]:
    adjacency: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    accepted = set(relations)
    for edge in edges:
        if accepted and edge["relation"] not in accepted:
            continue
        adjacency[edge["source"]].append((edge["target"], edge))
        adjacency[edge["target"]].append((edge["source"], edge))
    return adjacency


def _expand(seed_ids: set[str], nodes: dict[str, dict], adjacency: dict[str, list[tuple[str, dict]]], hops: int) -> tuple[set[str], list[dict]]:
    visited = set(seed_ids)
    queue = deque((node_id, 0) for node_id in seed_ids)
    selected_edges: list[dict] = []
    while queue:
        node_id, depth = queue.popleft()
        if depth == hops:
            continue
        for neighbor, edge in adjacency[node_id]:
            if neighbor not in nodes:
                continue
            selected_edges.append(edge)
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
    return visited, selected_edges


def _chunk_view(chunk: dict, node_ids: list[str] | None = None) -> dict:
    result = {key: chunk[key] for key in ("repository", "path", "line_start", "line_end", "source_sha256", "text")}
    if node_ids:
        result["graph_node_ids"] = node_ids
    return result


def build_graph_contexts(graph: str | Path, digest: str | Path, output: str | Path, *, hops: int = 1,
                         limit: int = 100, relations: tuple[str, ...] = (), max_source_chunks: int = 6) -> int:
    if hops not in (1, 2):
        raise ValueError("hops must be 1 or 2")
    if limit < 1 or max_source_chunks < 1:
        raise ValueError("limit and max_source_chunks must be positive")
    nodes, edges = _normalise_graph(graph)
    mapped = _map_nodes_to_chunks(nodes, digest)
    adjacency = _adjacency(edges, relations)
    contexts: list[dict] = []
    for primary_id, primary_chunks in mapped.items():
        if not primary_chunks:
            continue
        visited, selected_edges = _expand({primary_id}, nodes, adjacency, hops)
        selected_chunks: list[dict] = []
        for node_id in [primary_id, *sorted(visited - {primary_id})]:
            selected_chunks.extend(mapped.get(node_id, [])[:1])
            if len(selected_chunks) >= max_source_chunks:
                break
        if not selected_chunks:
            continue
        primary = selected_chunks[0]
        contexts.append({
            "id": f"graph:{primary_id}:{primary['repository']}:{primary['path']}:{primary['line_start']}",
            "review_status": "needs_human_review",
            "primary_node": nodes[primary_id],
            "graph_nodes": [nodes[node_id] for node_id in sorted(visited)],
            "graph_edges": selected_edges,
            "source": {"repository": primary["repository"], "path": primary["path"], "line_start": primary["line_start"],
                       "line_end": primary["line_end"], "lines": f"{primary['line_start']}-{primary['line_end']}", "source_sha256": primary["source_sha256"]},
            "source_chunks": [_chunk_view(chunk) for chunk in selected_chunks],
            "question_template": "Explain the cross-component flow or dependency shown by this graph and source context.",
        })
        if len(contexts) >= limit:
            break
    Path(output).write_text("".join(json.dumps(context, ensure_ascii=False) + "\n" for context in contexts), encoding="utf-8")
    return len(contexts)


def build_graph_chunks(graph: str | Path, digest: str | Path, output: str | Path, *, hops: int = 1,
                       limit: int = 100, relations: tuple[str, ...] = (), max_related_chunks: int = 6,
                       balanced_by_repository: bool = False) -> int:
    """Create chunk-first packages enriched with related Graphify symbols and source code.

    Unlike graph-context (which starts from a graph node), this preserves a primary
    source chunk and all symbols located inside it. It is the preferred input for
    Q&A generation because the model receives both code bodies and graph context.
    """
    if hops not in (1, 2):
        raise ValueError("hops must be 1 or 2")
    if limit < 1 or max_related_chunks < 1:
        raise ValueError("limit and max_related_chunks must be positive")
    nodes, edges = _normalise_graph(graph)
    mapped = _map_nodes_to_chunks(nodes, digest)
    by_primary: dict[str, tuple[dict, list[str]]] = {}
    for node_id, node_chunks in mapped.items():
        if not node_chunks:
            continue
        chunk = node_chunks[0]
        key = f"{chunk['repository']}:{chunk['path']}:{chunk['line_start']}"
        if key not in by_primary:
            by_primary[key] = (chunk, [])
        by_primary[key][1].append(node_id)
    if balanced_by_repository:
        # A lexical path sort puts one service (for example, bms) ahead of all
        # others. Select keys round-robin before materialising potentially large
        # source contexts, so a limited output represents each service.
        keys_by_repository: dict[str, list[str]] = defaultdict(list)
        for key in sorted(by_primary):
            keys_by_repository[by_primary[key][0]["repository"]].append(key)
        selected_keys: list[str] = []
        offset = 0
        while len(selected_keys) < limit:
            added = False
            for repository in sorted(keys_by_repository):
                candidates = keys_by_repository[repository]
                if offset < len(candidates):
                    selected_keys.append(candidates[offset])
                    added = True
                    if len(selected_keys) >= limit:
                        break
            if not added:
                break
            offset += 1
    else:
        selected_keys = sorted(by_primary)[:limit]
    adjacency = _adjacency(edges, relations)
    records: list[dict] = []
    for key in selected_keys:
        primary, primary_ids = by_primary[key]
        visited, selected_edges = _expand(set(primary_ids), nodes, adjacency, hops)
        related: list[dict] = [primary]
        related_ids: dict[str, list[str]] = {key: primary_ids}
        for node_id in sorted(visited - set(primary_ids)):
            for candidate in mapped.get(node_id, [])[:1]:
                candidate_key = f"{candidate['repository']}:{candidate['path']}:{candidate['line_start']}"
                if candidate_key not in related_ids and len(related) < max_related_chunks + 1:
                    related.append(candidate)
                    related_ids[candidate_key] = [node_id]
        records.append({
            "id": f"graph-chunk:{key}", "review_status": "needs_human_review",
            "source": {"repository": primary["repository"], "path": primary["path"], "line_start": primary["line_start"],
                       "line_end": primary["line_end"], "lines": f"{primary['line_start']}-{primary['line_end']}", "source_sha256": primary["source_sha256"]},
            "primary_node": nodes[primary_ids[0]], "primary_nodes": [nodes[node_id] for node_id in sorted(primary_ids)],
            "graph_nodes": [nodes[node_id] for node_id in sorted(visited)], "graph_edges": selected_edges,
            "source_chunks": [_chunk_view(chunk, related_ids[f"{chunk['repository']}:{chunk['path']}:{chunk['line_start']}"]) for chunk in related],
            "question_template": "Explain the primary code and its related functions or services using graph relationships and cited source code.",
        })
    Path(output).write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
    return len(records)
