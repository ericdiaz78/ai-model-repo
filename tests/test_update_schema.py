import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.update_schema import validate_models
SCHEMA_PATH = ROOT / 'schema.json'
MODELS_PATH = ROOT / 'models.json'
SCRIPT_PATH = ROOT / 'scripts' / 'update_schema.py'


class UpdateSchemaTests(unittest.TestCase):
    def test_validate_models_passes_seed_data(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        models = json.loads(MODELS_PATH.read_text())
        self.assertEqual(validate_models(models, schema), [])

    def test_validate_models_catches_bad_provider(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        models = json.loads(MODELS_PATH.read_text())
        broken = copy.deepcopy(models)
        broken[0]['provider'] = 'bad-provider'
        errors = validate_models(broken, schema)
        self.assertTrue(any('invalid provider' in err for err in errors))

    def test_validate_command_succeeds(self):
        result = subprocess.run(
            ['python3', str(SCRIPT_PATH), 'validate'],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('"ok": true', result.stdout.lower())


if __name__ == '__main__':
    unittest.main()
