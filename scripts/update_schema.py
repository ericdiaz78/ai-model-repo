#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / 'schema.json'
MODELS_PATH = ROOT / 'models.json'


def load_json(path: Path):
    return json.loads(path.read_text())


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def validate_models(models, schema):
    errors = []
    if schema.get('type') != 'array' or not isinstance(models, list):
        return ['Top-level data must be an array']

    item_schema = schema.get('items', {})
    required = item_schema.get('required', [])
    properties = item_schema.get('properties', {})
    provider_enum = set(properties.get('provider', {}).get('enum', []))

    for idx, model in enumerate(models):
        if not isinstance(model, dict):
            errors.append(f'[{idx}] item must be an object')
            continue
        for field in required:
            if field not in model:
                errors.append(f'[{idx}] missing required field: {field}')
        provider = model.get('provider')
        if provider is not None and provider not in provider_enum:
            errors.append(f'[{idx}] invalid provider: {provider}')
        context_window = model.get('context_window')
        if context_window is not None and not isinstance(context_window, int):
            errors.append(f'[{idx}] context_window must be an integer')
        pricing = model.get('pricing')
        if pricing is not None:
            if not isinstance(pricing, dict):
                errors.append(f'[{idx}] pricing must be an object')
            else:
                for key in ('input_per_mtok', 'output_per_mtok'):
                    value = pricing.get(key)
                    if value is not None and not isinstance(value, (int, float)):
                        errors.append(f'[{idx}] pricing.{key} must be numeric')
        meta = model.get('_meta')
        if meta is not None:
            confidence = meta.get('confidence')
            if confidence is not None and not (0 <= confidence <= 1):
                errors.append(f'[{idx}] _meta.confidence must be between 0 and 1')
    return errors


def add_provider(schema, provider):
    provider_enum = schema['items']['properties']['provider']['enum']
    if provider not in provider_enum:
        provider_enum.append(provider)
        provider_enum.sort()
        save_json(SCHEMA_PATH, schema)
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description='Schema validation and maintenance helper')
    sub = parser.add_subparsers(dest='cmd', required=True)

    validate = sub.add_parser('validate', help='Validate models.json against schema.json')
    validate.add_argument('--models', default=str(MODELS_PATH))
    validate.add_argument('--schema', default=str(SCHEMA_PATH))

    provider = sub.add_parser('add-provider', help='Add a provider enum to schema.json')
    provider.add_argument('provider')

    args = parser.parse_args()

    if args.cmd == 'validate':
        models = load_json(Path(args.models))
        schema = load_json(Path(args.schema))
        errors = validate_models(models, schema)
        if errors:
            print(json.dumps({'ok': False, 'errors': errors}, indent=2))
            sys.exit(1)
        print(json.dumps({'ok': True, 'models': len(models)}, indent=2))
        return

    if args.cmd == 'add-provider':
        schema = load_json(SCHEMA_PATH)
        changed = add_provider(schema, args.provider)
        print(json.dumps({'ok': True, 'provider': args.provider, 'changed': changed}, indent=2))


if __name__ == '__main__':
    main()
