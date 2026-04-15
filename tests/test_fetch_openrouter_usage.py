import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import fetch_openrouter_usage as usage_sync


class FetchOpenRouterUsageTests(unittest.TestCase):
    def test_merge_spend_history_replaces_overlapping_day_bucket(self):
        history = {
            'openai/gpt-4o-mini': [
                {
                    'date': '2026-04-15',
                    'cost_usd': 1.23,
                    'input_tokens': 100,
                    'output_tokens': 20,
                    'calls': 2,
                }
            ]
        }

        usage_sync.merge_spend_history(history, 'openai/gpt-4o-mini', {
            '2026-04-15': {
                'cost_usd': 0.5,
                'input_tokens': 40,
                'output_tokens': 10,
                'calls': 1,
            },
            '2026-04-16': {
                'cost_usd': 0.75,
                'input_tokens': 60,
                'output_tokens': 15,
                'calls': 1,
            },
        })

        self.assertEqual(
            history['openai/gpt-4o-mini'],
            [
                {
                    'date': '2026-04-15',
                    'cost_usd': 0.5,
                    'input_tokens': 40,
                    'output_tokens': 10,
                    'calls': 1,
                },
                {
                    'date': '2026-04-16',
                    'cost_usd': 0.75,
                    'input_tokens': 60,
                    'output_tokens': 15,
                    'calls': 1,
                },
            ],
        )

    def test_summarize_history_returns_canonical_totals(self):
        summary = usage_sync.summarize_history([
            {
                'date': '2026-04-14',
                'cost_usd': 1.25,
                'input_tokens': 1000000,
                'output_tokens': 250000,
                'calls': 5,
            },
            {
                'date': '2026-04-15',
                'cost_usd': 0.75,
                'input_tokens': 500000,
                'output_tokens': 125000,
                'calls': 3,
            },
        ])

        self.assertEqual(summary['total_cost_usd'], 2.0)
        self.assertEqual(summary['total_input_mtok'], 1.5)
        self.assertEqual(summary['total_output_mtok'], 0.375)
        self.assertEqual(summary['call_count'], 8)
        self.assertEqual(summary['period_start'], '2026-04-14')
        self.assertEqual(summary['period_end'], '2026-04-15')

    def test_overlapping_sync_window_is_idempotent(self):
        sample_records = [
            {
                'model_permaslug': 'minimax/minimax-m2.7',
                'usage': 0.3,
                'prompt_tokens': 1000,
                'completion_tokens': 100,
                'requests': 2,
                'date': '2026-04-15T10:00:00Z',
            },
            {
                'model_permaslug': 'minimax/minimax-m2.7',
                'usage': 0.2,
                'prompt_tokens': 600,
                'completion_tokens': 60,
                'requests': 1,
                'date': '2026-04-15T11:00:00Z',
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            models_path = tmp_path / 'models.json'
            history_path = tmp_path / 'spend_history.json'
            state_path = tmp_path / '.usage-sync-state.json'

            models = json.loads((ROOT / 'models.json').read_text())
            target = next(m for m in models if m['model_id'] == 'minimax/minimax-m2.7')
            target['spend'] = {}
            models_path.write_text(json.dumps([target], indent=2) + '\n')
            history_path.write_text('{}\n')

            original_models = usage_sync.MODELS_FILE
            original_history = usage_sync.SPEND_HISTORY_FILE
            original_state = usage_sync.STATE_FILE
            original_key = usage_sync.get_management_key
            original_credits = usage_sync.fetch_credits
            original_activity = usage_sync.fetch_activity

            try:
                usage_sync.MODELS_FILE = models_path
                usage_sync.SPEND_HISTORY_FILE = history_path
                usage_sync.STATE_FILE = state_path
                usage_sync.get_management_key = lambda: 'test-key'
                usage_sync.fetch_credits = lambda key: {'total_usage': 10, 'total_credits': 20}
                usage_sync.fetch_activity = lambda key, start_ts, end_ts=None, limit=1000: copy.deepcopy(sample_records)

                argv = sys.argv[:]
                sys.argv = ['fetch_openrouter_usage.py', '--since', '2026-04-15', '--quiet']
                usage_sync.main()
                first_models = json.loads(models_path.read_text())
                first_history = json.loads(history_path.read_text())

                sys.argv = ['fetch_openrouter_usage.py', '--since', '2026-04-15', '--quiet']
                usage_sync.main()
                second_models = json.loads(models_path.read_text())
                second_history = json.loads(history_path.read_text())
            finally:
                sys.argv = argv
                usage_sync.MODELS_FILE = original_models
                usage_sync.SPEND_HISTORY_FILE = original_history
                usage_sync.STATE_FILE = original_state
                usage_sync.get_management_key = original_key
                usage_sync.fetch_credits = original_credits
                usage_sync.fetch_activity = original_activity

        self.assertEqual(first_models, second_models)
        self.assertEqual(first_history, second_history)
        spend = second_models[0]['spend']
        self.assertEqual(spend['total_cost_usd'], 0.5)
        self.assertEqual(spend['call_count'], 3)
        self.assertEqual(second_history['minimax/minimax-m2.7'][0]['cost_usd'], 0.5)


if __name__ == '__main__':
    unittest.main()
