#!/usr/bin/env python3
import argparse
import json
import re
from datetime import datetime, UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS_PATH = ROOT / 'models.json'
PROVIDERS = ['openai', 'anthropic', 'google', 'deepseek', 'mistral', 'meta']


def infer_provider(text: str) -> str:
    low = text.lower()
    for provider in PROVIDERS:
        if provider in low:
            return provider
    return 'other'


def infer_model_name(text: str, provider: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        first = lines[0]
        if provider != 'other' and first.lower().startswith(provider):
            return first[len(provider):].strip(' :-') or 'Unknown Model'
        return first[:80]
    return 'Unknown Model'


def infer_context_window(text: str) -> int:
    match = re.search(r'(\d[\d,]*)\s*[kK]\s*(?:token|context)', text)
    if match:
        return int(match.group(1).replace(',', '')) * 1000
    match = re.search(r'(\d[\d,]*)\s*(?:token|context)', text)
    if match:
        return int(match.group(1).replace(',', ''))
    return 0


def infer_pricing(text: str) -> tuple[float, float]:
    amounts = [float(val) for val in re.findall(r'\$(\d+(?:\.\d+)?)', text)]
    if len(amounts) >= 2:
        return amounts[0], amounts[1]
    return 0.0, 0.0


def infer_modalities(text: str) -> list[str]:
    low = text.lower()
    modalities = ['text']
    for modality in ['image', 'audio', 'video', 'code']:
        if modality in low and modality not in modalities:
            modalities.append(modality)
    return modalities


def infer_routing_tags(text: str) -> list[str]:
    low = text.lower()
    tags = []
    for needle, tag in [
        ('coding', 'coding'),
        ('code', 'code'),
        ('reasoning', 'reasoning'),
        ('analysis', 'analysis'),
        ('fast', 'fast-response'),
        ('speed', 'fast-response'),
        ('cheap', 'low-cost'),
        ('low cost', 'low-cost'),
        ('summary', 'summarization'),
        ('summarization', 'summarization'),
        ('vision', 'vision'),
    ]:
        if needle in low and tag not in tags:
            tags.append(tag)
    return tags


def load_models(path: Path = DEFAULT_MODELS_PATH) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save_models(path: Path, models: list[dict]) -> None:
    path.write_text(json.dumps(models, indent=2) + '\n')


def merge_model_records(existing: list[dict], incoming: dict) -> list[dict]:
    merged = list(existing)
    for idx, model in enumerate(merged):
        if model.get('model_id') == incoming.get('model_id'):
            merged[idx] = incoming
            break
    else:
        merged.append(incoming)
    merged.sort(key=lambda model: model.get('model_id', ''))
    return merged


def ingest(text: str) -> dict:
    provider = infer_provider(text)
    model_name = infer_model_name(text, provider)
    model_slug = re.sub(r'[^a-z0-9]+', '-', model_name.lower()).strip('-') or 'unknown-model'
    input_cost, output_cost = infer_pricing(text)
    return {
        'model_id': f"{provider}/{model_slug}",
        'provider': provider,
        'model_name': model_name,
        'version': '',
        'release_date': datetime.now(UTC).date().isoformat(),
        'strengths': [],
        'weaknesses': [],
        'ideal_use_cases': [],
        'pricing': {
            'model': model_name,
            'input_per_mtok': input_cost,
            'output_per_mtok': output_cost,
            'notes': 'parsed from free text',
        },
        'context_window': infer_context_window(text),
        'modalities': infer_modalities(text),
        'performance_notes': text[:240],
        'routing_tags': infer_routing_tags(text),
        '_meta': {
            'last_updated': datetime.now(UTC).isoformat(),
            'source': 'ingest.py',
            'confidence': 0.35,
        },
    }


def ingest_to_path(text: str, out_path: Path) -> dict:
    record = ingest(text)
    merged = merge_model_records(load_models(out_path), record)
    save_models(out_path, merged)
    return record


def main():
    parser = argparse.ArgumentParser(description='Parse model release notes or free text into a record')
    parser.add_argument('text', nargs='?', help='Free text to parse')
    parser.add_argument('--file', help='Optional file to read instead')
    parser.add_argument('--out', help='Optional models.json file to upsert into')
    args = parser.parse_args()
    text = args.text or ''
    if args.file:
        with open(args.file) as f:
            text = f.read()
    record = ingest_to_path(text, Path(args.out)) if args.out else ingest(text)
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
