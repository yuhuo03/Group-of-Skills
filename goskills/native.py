"""Read a verified official GoS checkpoint through its loader, entirely offline.

Imports of GoS/native dependencies are delayed to an isolated subprocess whose
working directory has no .env. The official loader operates only on a scratch
copy. No constructor, linker, retrieval provider or compatibility fallback runs.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

OFFICIAL_COMMIT = "203f60a2c689da055ce1ac351eb3cb9912a3bca7"
EDGE_TYPES = {"dependency": "dep", "workflow": "workflow", "semantic": "semantic", "alternative": "alternative"}


def _read_json(path):
    def reject(value):
        raise ValueError(f"Non-finite JSON number in {path}: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_hash(root):
    # Matches the active baseline preparation library/workspace hash algorithm.
    root = Path(root)
    rows = [(path.relative_to(root).as_posix(), _file_hash(path)) for path in sorted(root.rglob("*"))
            if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def _primitive(value):
    """Convert known scalar/container metadata explicitly; reject unknown objects."""
    if value is None:
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite native metadata")
        return float(value)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Native metadata object keys must be strings")
        return {key: _primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    if hasattr(value, "tolist"):
        return _primitive(value.tolist())
    if hasattr(value, "item"):
        return _primitive(value.item())
    raise ValueError(f"Unsupported native metadata type: {type(value).__name__}")


def _official_root():
    configured = os.environ.get("GOSKILLS_OFFICIAL_ROOT")
    if configured:
        candidates = [Path(configured)]
    else:
        root = Path(__file__).resolve().parents[2]
        candidates = [root / "gos-baseline", root / "graph-of-skills"]
        spec = importlib.util.find_spec("gos")
        if spec is not None and spec.origin:
            candidates.append(Path(spec.origin).parent.parent)
    for candidate in candidates:
        candidate = candidate.resolve()
        if not (candidate / "gos/core/engine.py").is_file():
            continue
        try:
            commit = subprocess.check_output(["git", "-C", str(candidate), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
            dirty = subprocess.check_output(["git", "-C", str(candidate), "status", "--porcelain"], text=True)
        except (OSError, subprocess.CalledProcessError):
            continue
        if commit != OFFICIAL_COMMIT:
            continue
        if dirty.strip():
            raise ValueError("Official GoS checkout is dirty; export requires the frozen clean source")
        return candidate
    raise ValueError(f"Cannot find clean official GoS {OFFICIAL_COMMIT}; set GOSKILLS_OFFICIAL_ROOT")


def _index_header(workspace):
    paths = sorted(Path(workspace).glob("entities_hnsw_index_*.bin"))
    if len(paths) != 1:
        raise ValueError("Expected one native HNSW entity index")
    path = paths[0]
    with path.open("rb") as handle:
        header = handle.read(48)
    if len(header) != 48:
        raise ValueError("Truncated native HNSW header")
    offset, capacity, count, size, label_offset, data_offset = struct.unpack("<6Q", header)
    if (offset != 0 or count > capacity or not 0 < data_offset < label_offset < size or
            (label_offset - data_offset) % 4 or path.stat().st_size < 48 + count * size):
        raise ValueError("Unsupported native HNSW 64-bit little-endian float32 layout")
    if int(path.stem.removeprefix("entities_hnsw_index_")) != (label_offset - data_offset) // 4:
        raise ValueError("Native HNSW filename and actual header dimensions disagree")
    return {"path": str(path), "count": count, "dim": (label_offset - data_offset) // 4,
            "sha256": _file_hash(path), "header_layout": "hnswlib little-endian 64-bit size_t / float32"}


def _failures(value):
    if not isinstance(value, dict):
        raise ValueError("Malformed provider usage ledger")
    if "calls" in value:
        if type(value.get("calls")) is not int or type(value.get("failures")) is not int or min(value["calls"], value["failures"]) < 0:
            raise ValueError("Provider stage lacks explicit valid calls/failures")
        return value["failures"], 1
    records = [_failures(item) for item in value.values()]
    return sum(record[0] for record in records), sum(record[1] for record in records)


def _resolve_source(source, skills_root, files):
    if not isinstance(source, str) or not source:
        raise ValueError("Native node is missing its source path")
    source = source.replace("\\", "/")
    root = Path(skills_root)
    path = Path(source)
    if path.is_absolute():
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = None
    else:
        relative = path.as_posix()
    if relative in files:
        return relative, "library_relative"
    parts = path.parts
    for index, part in enumerate(parts):
        if part == root.name:
            relative = Path(*parts[index + 1:]).as_posix()
            if relative in files:
                return relative, "recorded_library_component"
    matches = [relative for relative in files if Path(relative).parent.name == path.parent.name]
    if len(matches) == 1:
        return matches[0], "unique_recorded_source_directory"
    raise ValueError(f"Native source is absent/ambiguous in the frozen skillset: {source}")


def _load_scratch(spec):
    """Worker only: use the official loader on a scratch checkpoint, never source."""
    sys.path.insert(0, spec["official_root"])
    from gos.core.engine import SkillGraphRAG
    from gos.core.parsing import parse_skill_document
    from gos.core.schema import SkillEdge
    import hnswlib
    import numpy as np

    class NoLLM:
        model = "offline-disabled"
        async def send_message(self, *args, **kwargs):
            raise RuntimeError("Native export forbids provider calls")

    class NoEmbedding:
        model = spec["model"]
        embedding_dim = spec["dim"]
        async def encode(self, *args, **kwargs):
            raise RuntimeError("Native export forbids provider calls")

    import asyncio
    async def load():
        engine = SkillGraphRAG(config=SkillGraphRAG.Config(
            llm_service=NoLLM(), embedding_service=NoEmbedding(),
            working_dir=spec["scratch_workspace"], prebuilt_working_dir=None,
            enable_query_rewrite=False, enable_semantic_linking=False))
        await engine.state_manager.query_start()
        try:
            nodes = await engine._load_all_nodes()
            raw_graph = engine.state_manager.graph_storage._graph
            if raw_graph is None or not raw_graph.is_directed():
                raise ValueError("Official loader did not produce a directed graph")
            if len(nodes) != spec["count"] or raw_graph.vcount() != spec["count"] or raw_graph.ecount() != spec["edge_count"]:
                raise ValueError("Loaded node/edge counts differ from the verified construction report")
            index = hnswlib.Index(space="cosine", dim=spec["dim"])
            index.load_index(str(Path(spec["scratch_workspace"]) / Path(spec["index_path"]).name))
            if int(index.get_current_count()) != len(nodes) or {int(value) for value in index.get_ids_list()} != set(range(len(nodes))):
                raise ValueError("Native vector labels/count do not match graph vertex IDs")
            # Shape is obtained from actual vectors, not only the binary filename.
            vectors = index.get_items(list(range(len(nodes))))
            actual_shape = vectors.shape
            if tuple(actual_shape) != (len(nodes), spec["dim"]) or not np.isfinite(vectors).all():
                raise ValueError("Actual stored vector dimension/finite-value mismatch")
            root = Path(spec["skills_root"])
            files = {path.relative_to(root).as_posix(): path for path in root.rglob("SKILL.md") if path.is_file()}
            skills, ids_by_vertex, names, sources = [], [], set(), set()
            for vertex_id, node in enumerate(nodes):
                vertex = raw_graph.vs[vertex_id]
                if node.name != vertex["name"] or node.name in names:
                    raise ValueError("Native loader vertex ordering or unique-name invariant failed")
                if not isinstance(node.description, str) or not node.description.strip():
                    raise ValueError("Native node lacks a nonempty description")
                names.add(node.name)
                relative, resolution = _resolve_source(node.source_path, root, files)
                if relative in sources:
                    raise ValueError("Two native nodes resolve to the same canonical skill file")
                sources.add(relative)
                raw = files[relative].read_bytes()
                text = raw.decode("utf-8")
                indexed_text = text.replace("\r\n", "\n").replace("\r", "\n")
                if not node.raw_content or node.raw_content != indexed_text:
                    raise ValueError(f"Native indexed skill text differs from frozen source: {relative}")
                parsed = parse_skill_document(text, source_path=str(files[relative]))
                if parsed is None or parsed.name != node.name or not parsed.body.strip():
                    raise ValueError(f"Official document parser/name/body mismatch: {relative}")
                attrs = dict(vertex.attributes())
                metadata_json = attrs.pop("metadata_json", "{}")
                metadata = json.loads(metadata_json or "{}")
                if not isinstance(metadata, dict):
                    raise ValueError("Native metadata_json must be an object")
                attrs.pop("raw_content", None)
                ids_by_vertex.append(relative)
                skills.append({"id": relative, "name": node.name, "description": node.description,
                               "text": text, "body": parsed.body, "source_path": relative,
                               "metadata": _primitive({"native_metadata": metadata, "upstream_vertex_attrs": attrs,
                                                       "graph_vertex_id": vertex_id, "upstream_skill_id": node.skill_id,
                                                       "upstream_source_path": node.source_path, "source_resolution": resolution,
                                                       "source_sha256": hashlib.sha256(raw).hexdigest()})})
            if sources != set(files):
                raise ValueError("Native graph/source-document mapping is not bijective")
            edges = []
            for edge_id, edge in enumerate(raw_graph.es):
                attrs = dict(edge.attributes())
                for field in ("type", "weight", "confidence", "description", "provenance"):
                    if field not in attrs or attrs[field] is None:
                        raise ValueError(f"Native edge lacks explicit {field}")
                kind = attrs["type"]
                if not isinstance(kind, str) or kind not in EDGE_TYPES:
                    raise ValueError(f"Unknown/blank native edge type: {kind!r}")
                weight, confidence = float(attrs["weight"]), float(attrs["confidence"])
                if isinstance(attrs["weight"], bool) or not math.isfinite(weight) or weight <= 0 or not math.isfinite(confidence):
                    raise ValueError("Native edge has non-finite or nonpositive weight/confidence")
                # Validate official typed-edge semantics without inventing defaults.
                SkillEdge(source=nodes[edge.source].name, target=nodes[edge.target].name,
                          type=kind, weight=weight, confidence=confidence,
                          description=attrs["description"], provenance=attrs["provenance"],
                          evidence=attrs.get("evidence", ""), validator_model=attrs.get("validator_model", ""))
                edges.append({"source": ids_by_vertex[edge.source], "target": ids_by_vertex[edge.target],
                              "type": EDGE_TYPES[kind], "weight": weight,
                              "metadata": _primitive({"upstream_edge_id": edge_id, "upstream_type": kind,
                                                      "upstream_source_vertex": int(edge.source), "upstream_target_vertex": int(edge.target),
                                                      "direction_mapping": "stored source->target preserved; dependency renamed dep only",
                                                      "upstream_edge_attrs": attrs})})
            return {"skills": skills, "edges": edges, "actual_vector_shape": list(actual_shape)}
        finally:
            await engine.state_manager.query_done()
    return asyncio.run(load())


def export_native(workspace: Path, skills_root: Path, index_run_dir: Path | None = None) -> dict:
    """Return a strict native graph export; original checkpoint and library stay unchanged."""
    workspace, skills_root = Path(workspace).resolve(), Path(skills_root).resolve()
    if not workspace.is_dir() or not skills_root.is_dir():
        raise ValueError("Native workspace and skillset directories must exist")
    if any(path.is_symlink() for path in workspace.rglob("*")):
        raise ValueError("Native checkpoint must not contain symlinks to mutable external state")
    official = _official_root()
    run_dir = Path(index_run_dir).resolve() if index_run_dir is not None else workspace
    report_path = run_dir / "construction_report.json"
    report = _read_json(report_path)
    files = {path.relative_to(skills_root).as_posix(): path for path in skills_root.rglob("SKILL.md") if path.is_file()}
    count = len(files)
    if not count or report.get("git_commit") != OFFICIAL_COMMIT or report.get("graph", {}).get("directed") is not True:
        raise ValueError("Construction report lacks the fixed commit/directness/nonempty source corpus")
    if report.get("nodes", {}).get("total") != count or type(report.get("edges", {}).get("total")) is not int or report["edges"]["total"] < 0:
        raise ValueError("Construction report/source counts disagree")
    failures, usage_stages = _failures(report.get("usage", {}))
    if not usage_stages or failures:
        raise ValueError("Construction usage is unverified or records provider failures")
    header = _index_header(workspace)
    if header["count"] != count:
        raise ValueError("Actual vector count does not match the source/report node count")
    params_path, status_path = run_dir / "index_parameters.json", run_dir / "INDEX_STATUS.json"
    params = _read_json(params_path) if params_path.is_file() else None
    status = _read_json(status_path) if status_path.is_file() else None
    if index_run_dir is not None and (params is None or status is None):
        raise ValueError("External index-run directory requires parameters and an explicit complete status")
    if status is not None and (status.get("status") != "complete" or status.get("final_nodes") != count or status.get("provider_failures") != 0):
        raise ValueError("Native index is not explicitly complete with zero provider failures")
    model = report.get("models", {}).get("embedding")
    if not isinstance(model, str) or not model:
        raise ValueError("Construction report lacks the embedding model")
    if params is not None:
        if (params.get("git_commit") != OFFICIAL_COMMIT or params.get("embedding_dim") != header["dim"] or
                params.get("expected_nodes") != count or params.get("valid_documents") != count or
                params.get("unique_skill_names") != count or params.get("duplicate_names") or
                Path(params.get("workspace", "")).resolve() != workspace or
                str(params.get("embedding_model", "")).removeprefix("openai/") != model.removeprefix("openai/")):
            raise ValueError("Index parameters differ from the actual model/dimension/workspace/source corpus")
        records = params.get("input_manifest")
        if not isinstance(records, list) or len(records) != count:
            raise ValueError("Missing complete native source-document manifest")
        seen = set()
        for record in records:
            relative = record.get("path")
            if relative not in files or relative in seen:
                raise ValueError("Native source manifest has unknown/duplicate paths")
            seen.add(relative)
            text = files[relative].read_text(encoding="utf-8").encode()
            if len(text) != record.get("bytes") or hashlib.sha256(text).hexdigest() != record.get("sha256"):
                raise ValueError(f"Native source-document hash mismatch: {relative}")
        if seen != set(files):
            raise ValueError("Native source manifest does not cover the full library")
    workspace_hash, library_hash = _tree_hash(workspace), _tree_hash(skills_root)
    evidence = {str(path): _file_hash(path) for path in (report_path, params_path, status_path) if path.is_file()}
    with tempfile.TemporaryDirectory(prefix="goskills-native-export-") as temporary:
        scratch = Path(temporary)
        checkpoint, cwd = scratch / "checkpoint", scratch / "empty-cwd"
        shutil.copytree(workspace, checkpoint)
        cwd.mkdir()
        spec = {"official_root": str(official), "scratch_workspace": str(checkpoint), "skills_root": str(skills_root),
                "index_path": header["path"], "model": model, "dim": header["dim"], "count": count,
                "edge_count": report["edges"]["total"]}
        env = {key: value for key, value in os.environ.items()
               if not any(marker in key.upper() for marker in ("API_KEY", "APIKEY", "TOKEN", "PASSWORD", "SECRET"))}
        env.update(PYTHONPATH=str(official), PYTHONDONTWRITEBYTECODE="1", GOS_WORKING_DIR=str(checkpoint),
                   GOS_PREBUILT_WORKING_DIR="", GOS_ENABLE_QUERY_REWRITE="false", GOS_EMBEDDING_DIM=str(header["dim"]))
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--native-export-worker"],
                                    input=json.dumps(spec), text=True, capture_output=True, cwd=cwd, env=env, timeout=180)
        finally:
            if _tree_hash(workspace) != workspace_hash or _tree_hash(skills_root) != library_hash or any(_file_hash(path) != digest for path, digest in evidence.items()):
                raise ValueError("Source workspace/library/evidence changed during export; no graph returned")
        if result.returncode:
            raise RuntimeError("Official scratch loader failed; use the frozen native environment. " + result.stderr[-2000:])
        loaded = json.loads(result.stdout)
    provenance = {"official_commit": OFFICIAL_COMMIT, "official_root": str(official), "model": model, "dim": header["dim"],
                  "report": {"path": str(report_path), "sha256": evidence[str(report_path)]},
                  "workspace": str(workspace), "workspace_hash": workspace_hash,
                  "library_root": str(skills_root), "library_hash": library_hash, "evidence_file_hashes": evidence,
                  "hash_algorithm": "sha256 of compact JSON sorted (relative path, file sha256) pairs; .git/__pycache__ excluded",
                  "provider_failures": failures, "source_document_count": count,
                  "actual_vector_shape": loaded["actual_vector_shape"], "actual_hnsw": header,
                  "loader": "official SkillGraphRAG._load_all_nodes + raw directed graph, scratch-only",
                  "edge_export_policy": "preserve every stored edge and direction; dependency label maps to dep; no canonicalization or deduplication",
                  "provider_calls_performed": 0, "source_workspace_unchanged": True}
    graph = {"schema_version": 1, "kind": "goskills_graph", "provenance": provenance,
             "skills": loaded["skills"], "edges": loaded["edges"]}
    return _primitive(graph)


if __name__ == "__main__" and sys.argv[1:] == ["--native-export-worker"]:
    print(json.dumps(_load_scratch(json.loads(sys.stdin.read())), ensure_ascii=False, allow_nan=False))
