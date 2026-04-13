import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ingest import ingest, merge_model_records, save_models
from scripts.query import query


class IngestQueryTests(unittest.TestCase):
    def test_merge_model_records_updates_existing_model(self):
        existing = [
            {
                'model_id': 'openai/gpt-4o',
                'provider': 'openai',
                'model_name': 'GPT-4o',
                'routing_tags': ['vision'],
                'pricing': {'output_per_mtok': 15.0},
            }
        ]
        incoming = {
            'model_id': 'openai/gpt-4o',
            'provider': 'openai',
            'model_name': 'GPT-4o Updated',
            'routing_tags': ['vision', 'analysis'],
            'pricing': {'output_per_mtok': 12.0},
        }
        merged = merge_model_records(existing, incoming)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['model_name'], 'GPT-4o Updated')
        self.assertEqual(merged[0]['pricing']['output_per_mtok'], 12.0)

    def test_save_and_query_custom_models_file(self):
        record = ingest('OpenAI GPT-4.1 mini cheap code model with 128k context and $0.4 $1.6 pricing')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'models.json'
            save_models(out, [record])
            result = query('cheap code model', models_path=out)
            self.assertIn(record['model_name'], result)
            self.assertIn(record['model_id'], result)


if __name__ == '__main__':
    unittest.main()
