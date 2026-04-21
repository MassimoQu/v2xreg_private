import unittest
from pathlib import Path


class ProjectV2SyncExtractionTest(unittest.TestCase):
    def test_extracts_tasks_and_docs_from_ops_markdown(self):
        repo_root = Path(__file__).resolve().parents[2]
        sources = [
            repo_root / "docs" / "operations" / "benchmark_pending_runs_and_plan_20260224.md",
            repo_root / "docs" / "operations" / "WORKTREE_STATE.md",
        ]

        from tools.projectv2_sync.extract import extract_items

        items = extract_items(sources, repo_root=repo_root)
        self.assertGreater(len(items), 0)

        tasks = [it for it in items if it.item_type == "task"]
        docs = [it for it in items if it.item_type == "doc"]
        self.assertGreaterEqual(len(tasks), 1)
        self.assertGreaterEqual(len(docs), 1)

        # A couple of anchor tasks we expect from the minimal checklist set.
        titles = {t.title for t in tasks}
        self.assertTrue(any(t.startswith("P0-2)") for t in titles))
        self.assertTrue(any(t.startswith("B) ") for t in titles))

        # Run ids should be "run ids", not doc stems or paths.
        for t in tasks:
            for rid in t.run_ids:
                self.assertNotIn("/", rid)
                self.assertFalse(rid.endswith(".md"))
                self.assertFalse(rid.endswith(".py"))

        # The canonical fullbench task should have dependencies wired.
        b = next((t for t in tasks if t.title.startswith("B) ")), None)
        self.assertIsNotNone(b)
        self.assertGreaterEqual(len(b.depends_on), 1)


if __name__ == "__main__":
    unittest.main()

