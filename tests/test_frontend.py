import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendContractTests(unittest.TestCase):
    def test_timeline_controls_and_curve_link_are_wired(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="flightTimeline"', html)
        self.assertIn('data-timeline-scope="important"', html)
        self.assertIn('id="timelineCategory"', html)
        self.assertIn("function renderTimeline(", javascript)
        self.assertIn("function jumpToTimelineTime(", javascript)
        self.assertIn("function addTimelineFields(", javascript)
        self.assertIn("resolveTimelineField", javascript)


if __name__ == "__main__":
    unittest.main()
