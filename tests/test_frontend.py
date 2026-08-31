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
        self.assertIn('"magnetometer": ["未见明显异常"', javascript)
        self.assertIn('class="experimental-badge"', javascript)
        self.assertIn('class="evidence-value-wrap"', javascript)
        self.assertIn('data-full-value="${escapeHtml(fullValue)}"', javascript)
        self.assertIn("function showEvidenceTooltip(", javascript)
        self.assertIn('tooltip.id = "evidenceFloatingTooltip"', javascript)
        self.assertIn("const fullValue = item.full_value || item.value", javascript)
        self.assertIn("function updateAnomalyWindowControls(", javascript)
        self.assertIn("function toggleAnomalyWindows(", javascript)
        self.assertIn('data-anomaly-more', javascript)
        styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".evidence-value {", styles)
        self.assertIn(".evidence { box-sizing: border-box; min-width: 0", styles)
        self.assertIn(".evidence-floating-tooltip.visible", styles)
        self.assertIn(".anomaly-window-hidden { display: none; }", styles)
        self.assertIn(".anomaly-more {", styles)
        self.assertIn(".explorer-legend .enum-tooltip { display: block", styles)
        self.assertIn(".explorer-legend .enum-grid { display: grid", styles)
        self.assertIn(".field-help-badge {", styles)
        self.assertIn(".field-option .enum-tooltip { display: none", styles)


if __name__ == "__main__":
    unittest.main()
