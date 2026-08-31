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
        self.assertIn("function enumFieldHelp(", javascript)
        self.assertIn("function curveFieldHelp(", javascript)
        self.assertIn('${curveFieldHelp(field.name, field)}', javascript)
        self.assertIn('${curveFieldHelp(field.key, field)}', javascript)
        self.assertIn('class="field-help-badge"', javascript)
        self.assertIn('title="${escapeHtml(nativeHint)}"', javascript)
        self.assertIn('self.send_header("Cache-Control", "no-store, max-age=0")', (ROOT / "app.py").read_text(encoding="utf-8"))
        self.assertIn("field.enum_title", javascript)
        self.assertIn("field.enum_note", javascript)
        self.assertIn("function decodeCurveValue(", javascript)
        self.assertIn('line.enumKind === "bitmask"', javascript)
        self.assertIn('line.enumKind === "annotation"', javascript)
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".explorer-legend .enum-tooltip { display: block", styles)
        self.assertIn(".explorer-legend .enum-grid { display: grid", styles)
        self.assertIn(".field-help-badge {", styles)
        self.assertIn(".field-option .enum-tooltip { display: none", styles)


if __name__ == "__main__":
    unittest.main()
