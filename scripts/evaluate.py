#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = json.loads((ROOT / 'models.json').read_text())


def _filter(required_tags=None, min_context_window=0):
    required_tags = set(required_tags or [])
    results = []
    for model in MODELS:
        tags = set(model.get('routing_tags', []))
        if required_tags and not required_tags.issubset(tags):
            continue
        if model.get('context_window', 0) < min_context_window:
            continue
        results.append(model)
    return results


def compare_models(task, models):
    picked = [m for m in MODELS if m['model_id'] in models]
    return {'task': task, 'models': picked}


def recommend_model(task, constraints):
    required_tags = constraints.get('required_tags', [])
    min_context = constraints.get('min_context_window', 0)
    candidates = _filter(required_tags, min_context)
    if not candidates:
        candidates = [m for m in MODELS if m.get('context_window', 0) >= min_context] or MODELS
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


def main():
    parser = argparse.ArgumentParser(description='Compare or recommend AI models')
    sub = parser.add_subparsers(dest='cmd', required=True)

    c = sub.add_parser('compare', help='Compare a set of models for a task')
    c.add_argument('--task', required=True)
    c.add_argument('--models', nargs='+', required=True)

    r = sub.add_parser('recommend', help='Recommend a model for a task')
    r.add_argument('--task', required=True)
    r.add_argument('--required-tags', nargs='*', default=[])
    r.add_argument('--min-context-window', type=int, default=0)

    args = parser.parse_args()
    if args.cmd == 'compare':
        print(json.dumps(compare_models(args.task, args.models), indent=2))
    else:
        print(json.dumps(recommend_model(args.task, {
            'required_tags': args.required_tags,
            'min_context_window': args.min_context_window,
        }), indent=2))


if __name__ == '__main__':
    main()
