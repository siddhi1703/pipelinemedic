import json
import tempfile
import unittest
from pathlib import Path

from pipelinemedic.dashboard import build, collect


class DashboardTests(unittest.TestCase):
    def test_missing_artifacts_still_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = build(tmp).read_text()
            self.assertIn("PipelineMedic Monitor", html)
            self.assertIsNone(collect(tmp)["pilot"])

    def test_artifacts_are_embedded_and_script_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "demo.json").write_text(json.dumps({"fault": "</script><b>x", "decision": {"decision": "accept"}}))
            html = build(tmp).read_text()
            self.assertNotIn("</script><b>x", html)
            self.assertIn("<\\/script><b>x", html)


if __name__ == "__main__":
    unittest.main()
