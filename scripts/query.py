#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODELS_PATH = ROOT / 'models.json'


def load_models(models_path: Path = DEFAULT_MODELS_PATH) -> list[dict]:
    return json.loads(models_path.read_text())


def recommend_model_from_dataset(task: str, constraints: dict, models: list[dict]) -> dict:
    required_tags = set(constraints.get('required_tags', []))
    min_context = constraints.get('min_context_window', 0)
    candidates = []
    for model in models:
        tags = set(model.get('routing_tags', []))
        if required_tags and not required_tags.issubset(tags):
            continue
        if model.get('context_window', 0) < min_context:
            continue
        candidates.append(model)
    if not candidates:
        candidates = [m for m in models if m.get('context_window', 0) >= min_context] or models

    task_l = task.lower()

    def first_match(predicate):
        for model in candidates:
            if predicate(model):
                return model
        return None

    if 'vision' in task_l or 'image' in task_l or 'multimodal' in task_l:
        match = first_match(lambda model: 'vision' in model.get('routing_tags', []))
        if not match:
            match = first_match(lambda model: 'image' in model.get('modalities', []))
        if match:
            return match

    if 'summary' in task_l or 'summariz' in task_l:
        match = first_match(lambda model: 'summarization' in model.get('routing_tags', []))
        if match:
            return match

    if 'long context' in task_l or 'large context' in task_l or '200k' in task_l:
        match = first_match(lambda model: model.get('context_window', 0) >= max(min_context, 200000))
        if match:
            return match

    if 'code' in task_l or 'coding' in task_l:
        match = first_match(lambda model: 'code' in model.get('routing_tags', []) or 'coding' in model.get('routing_tags', []))
        if match:
            return match

    if 'fast' in task_l or 'quick' in task_l:
        match = first_match(lambda model: 'fast-response' in model.get('routing_tags', []))
        if match:
            return match

    return sorted(candidates, key=lambda m: m.get('pricing', {}).get('output_per_mtok', 999))[0]


def query(nl_prompt: str, models_path: Path = DEFAULT_MODELS_PATH) -> str:
    prompt = nl_prompt.lower()
    required = []
    min_context_window = 0

    if 'low cost' in prompt or 'cheap' in prompt or 'budget' in prompt:
        required.append('low-cost')
    if 'coding' in prompt or 'code' in prompt:
        required.append('code')
    if 'summar' in prompt:
        required.append('summarization')
    if '200k' in prompt or 'long context' in prompt or 'large context' in prompt:
        min_context_window = 200000

    models = load_models(models_path)
    model = recommend_model_from_dataset(nl_prompt, {
        'required_tags': required,
        'min_context_window': min_context_window,
    }, models)
    tags = ', '.join(model.get('routing_tags', []))
    return f"{model['model_name']} ({model['model_id']}) — recommended for '{nl_prompt}'. Tags: [{tags}]. Context: {model.get('context_window')}"


def main():
    parser = argparse.ArgumentParser(description='Natural language model query helper')
    parser.add_argument('prompt', help='Natural language question')
    parser.add_argument('--models', default=str(DEFAULT_MODELS_PATH), help='Path to models dataset JSON')
    args = parser.parse_args()
    print(query(args.prompt, models_path=Path(args.models)))


if __name__ == '__main__':
    main()
