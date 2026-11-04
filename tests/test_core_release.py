"""Offline regression checks for the released experimental retrieval policy."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from goskills.config import validate_config
from goskills.groups import build_pool
from goskills.io import read_json, write_json
from goskills.presentation import extractive_body
from goskills.retrieval import Retriever
from goskills.validation import validate_bundle

ROOT = Path(__file__).resolve().parents[1]


def graph():
    return read_json(ROOT / "examples/minimal_graph.json")


class CoreReleaseTests(unittest.TestCase):
    def test_frozen_core_bytes(self):
        manifest = read_json(ROOT / "provenance/CORE_SOURCE.json")
        for item in manifest["files"]:
            digest = hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()
            self.assertEqual(digest, item["source_sha256"])
            self.assertEqual(digest, item["release_sha256"])

    def test_permutation_invariant_retrieval(self):
        original = graph()
        reverse = copy.deepcopy(original)
        reverse["skills"].reverse()
        reverse["edges"].reverse()
        query = "Use trimesh to parse STL and write JSON with deterministic unit tests."
        a = Retriever(build_pool(original, validate_config())).query(query)
        b = Retriever(build_pool(reverse, validate_config())).query(query)
        self.assertEqual(a["rendered_context"], b["rendered_context"])
        self.assertEqual(a["presented_skills"], b["presented_skills"])
        self.assertTrue(a["presented_skills"])
        validate_bundle(a)

    def test_unmatched_query_has_no_fabricated_anchor(self):
        bundle = Retriever(build_pool(graph(), validate_config())).query("zyzzyva quokka")
        self.assertEqual(bundle["presented_skills"], [])
        self.assertEqual(bundle["plan"], [])
        self.assertIsNone(bundle["anchor_skill_id"])
        validate_bundle(bundle)

    def test_context_cap_accounts_for_mount_paths(self):
        pool = build_pool(graph(), validate_config({"max_context_chars": 1100}))
        answer = Retriever(pool, source_root="/long/agent/mount/path/skills").query("Parse STL and output JSON")
        self.assertLessEqual(len(answer["rendered_context"]), 1100)
        validate_bundle(answer)

    def test_source_body_spans_are_extractive(self):
        source = "# Context\n" + "Background. " * 100 + "\n# JSON validation\nValidate the JSON schema before delivery.\n"
        body, spans = extractive_body(source, "JSON schema validation", 200)
        self.assertEqual(body, "\n\n".join(source[a:b] for a, b in spans))
        self.assertLessEqual(len(body), 200)
        self.assertIn("JSON schema", body)

    def test_uncovered_requirement_cannot_be_hidden(self):
        answer = Retriever(build_pool(graph(), validate_config())).query("Parse STL and write unique_report.json")
        self.assertTrue(answer["coverage_debt"])
        answer["rendered_context"] = answer["rendered_context"].rsplit("\nDEBT\n", 1)[0] + "\nDEBT\nNone.\n"
        answer["rendered_chars"] = len(answer["rendered_context"])
        with self.assertRaises(ValueError):
            validate_bundle(answer)

    def test_corrupt_pool_rejected(self):
        pool = build_pool(graph(), validate_config())
        pool["provenance"]["source_graph_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            Retriever(pool)

    def test_duplicate_sources_rejected(self):
        source = graph()
        source["skills"][1]["source_path"] = source["skills"][0]["source_path"]
        with self.assertRaises(ValueError):
            build_pool(source, validate_config())

    def test_output_refuses_to_replace_existing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "answer.json"
            write_json(output, {"original": True})
            with self.assertRaises(FileExistsError):
                write_json(output, {"original": False})
            self.assertEqual(read_json(output), {"original": True})

    def test_documented_cli_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool, bundle = Path(tmp) / "pool.json", Path(tmp) / "bundle.json"
            def run(*args):
                return subprocess.run([sys.executable, "-m", "goskills", *map(str, args)], cwd=ROOT,
                                      check=True, capture_output=True, text=True).stdout
            run("build", "--graph", ROOT / "examples/minimal_graph.json", "--output", pool)
            run("query", "--pool", pool, "--query", "Parse STL and output JSON", "--output-json", bundle)
            report = json.loads(run("validate-bundle", bundle))
            self.assertEqual(report["status"], "passed")
            self.assertGreater(report["presented_skills"], 0)


if __name__ == "__main__":
    unittest.main()
