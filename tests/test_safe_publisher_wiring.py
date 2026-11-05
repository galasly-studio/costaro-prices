"""Safety contract: research is read-only; publication is strictly gated."""

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
        self.assertIn("sourceHealth", workflow)
        self.assertIn("Доступность магазинов", workflow)
        self.assertIn("scripts/collect_prices.py", workflow)
        self.assertIn("verified_release_readiness.json", workflow)
        # Readiness must evaluate the live, independently approved catalog,
        # never the draft research baseline, and must refresh any old report.
        self.assertIn("--catalog published_catalog/prices.json", workflow)
        self.assertIn('mv verified_release_readiness.json "$RUNNER_TEMP/costaro_previous_readiness.json"', workflow)
        self.assertIn('--candidate "$RUNNER_TEMP/costaro_monthly_candidate/prices.json"', workflow)
        self.assertIn('--report verified_release_readiness.json', workflow)
        self.assertNotIn("git push", workflow)
        self.assertNotIn("actions/deploy-pages", workflow)

    def test_live_publisher_never_skips_approval_gates(self):
        directory = ROOT / ".github/workflows"
        inactive = directory / "approved-price-publisher.yml.disabled"
        self.assertTrue(inactive.is_file())
        workflow = directory / "approved-price-publisher.yml"
        self.assertTrue(workflow.is_file())
        contents = workflow.read_text(encoding="utf-8")
        self.assertIn("  schedule:\n", contents)
        self.assertIn("'17 6 3 * *'", contents)
        self.assertIn("scripts/prepare_verified_catalog_release.py", contents)
        self.assertIn("--catalog published_catalog/prices.json", contents)
        self.assertIn("Path('published_catalog/prices.json')", contents)
        self.assertIn("research.get('status') != 'draft'", contents)
        self.assertIn("automaticPublicationApproved", contents)
        self.assertIn("approvedMappings", contents)
        self.assertIn("catalog.get('status') == 'published'", contents)
        self.assertIn("report.get('status') == 'ready_for_guarded_publication'", contents)
        self.assertIn('if: steps.gate.outputs.publish == \'true\'', contents)
        self.assertIn('git add -- published_catalog/prices.json', contents)
        self.assertNotIn('git add -- prices.json', contents)
        self.assertIn('git push origin HEAD:main', contents)
        # A bot commit does not trigger branch-based Pages; a separately
        # permissioned deployment is allowed only after publication.
        self.assertIn("actions/deploy-pages@v4", contents)
        self.assertIn("actions/upload-pages-artifact@v4", contents)
        self.assertIn("if: needs.verify-and-publish.outputs.deploy == 'true'", contents)
        # Committed historical reports may never be overwritten by the job.
        self.assertIn("$RUNNER_TEMP/costaro_price_release_readiness.json", contents)

    def test_one_time_historical_bootstrap_never_edits_research_catalog(self):
        workflow = (ROOT / ".github/workflows/bootstrap-historical-price-feed.yml")
        contents = workflow.read_text(encoding="utf-8")
        self.assertIn("  workflow_dispatch:", contents)
        self.assertNotIn("  schedule:\n", contents)
        self.assertIn("scripts/verify_approved_historical_feed.py", contents)
        self.assertIn("published_catalog/prices.json", contents)
        self.assertIn("2026-08-30", contents)
        self.assertIn("actions/deploy-pages@v4", contents)
        self.assertNotIn("git push", contents)
        self.assertNotIn("git add -- prices.json", contents)


if __name__ == "__main__":
    unittest.main()
