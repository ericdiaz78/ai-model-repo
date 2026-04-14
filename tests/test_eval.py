import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate import compare_models, recommend_model


class EvaluateTests(unittest.TestCase):
    def test_compare_models_returns_models(self):
        result = compare_models("reasoning", ["anthropic/claude-sonnet-4-6", "openai/gpt-4o"])
        self.assertEqual(len(result["models"]), 2)

    def test_recommend_model_prefers_low_cost_code(self):
        result = recommend_model("coding", {"required_tags": ["code", "low-cost"]})
        tags = set(result.get("routing_tags", []))
        self.assertIn("low-cost", tags)
        self.assertTrue("code" in tags or "coding" in tags)

    def test_recommend_model_prefers_vision_for_image_task(self):
        result = recommend_model("vision image analysis", {})
        tags = set(result.get("routing_tags", []))
        modalities = set(result.get("modalities", []))
        self.assertTrue("vision" in tags or "image" in modalities)

    def test_recommend_model_prefers_summarization_for_summary_task(self):
        result = recommend_model("fast summary for cron", {})
        self.assertEqual(result["model_id"], "google/gemini-2.5-flash-lite")

    def test_recommend_model_respects_long_context_requirement(self):
        result = recommend_model("long context research", {"min_context_window": 200000})
        self.assertGreaterEqual(result["context_window"], 200000)


if __name__ == '__main__':
    unittest.main()
