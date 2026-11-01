"""Safety contract: monthly checks are read-only; publisher remains opt-in."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkflowWiringTests(unittest.TestCase):
    def test_monthly_workflow_never_promotes_or_pushes(self):
        workflow = (ROOT / ".github/workflows/monthly-price-audit.yml").read_text(
            encoding="utf-8")
        self.assertIn("contents: read", workflow)
        self.assertIn("  push:\n", workflow)
        self.assertIn("scripts/prepare_verified_catalog_release.py", workflow)
        self.assertIn("GITHUB_STEP_SUMMARY", workflow)
        self.assertIn("verified_release_readiness.json", workflow)
        self.assertNotIn("git push", workflow)
        self.assertNotIn("actions/deploy-pages", workflow)

    def test_live_publisher_is_inactive_until_explicit_activation(self):
        directory = ROOT / ".github/workflows"
        inactive = directory / "approved-price-publisher.yml.disabled"
        self.assertTrue(inactive.is_file())
        self.assertFalse((directory / "approved-price-publisher.yml").exists())
        contents = inactive.read_text(encoding="utf-8")
        self.assertIn("approved-price-publisher.yml", contents)
        self.assertIn("scripts/prepare_verified_catalog_release.py", contents)
        self.assertIn("actions/deploy-pages@v4", contents)
        self.assertIn("actions/upload-pages-artifact@v4", contents)
        self.assertIn("automaticPublicationApproved", contents)


if __name__ == "__main__":
    unittest.main()
