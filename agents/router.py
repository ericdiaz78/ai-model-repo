#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from evaluate import recommend_model


def get_recommended_model(task_description: str, context_window_needed: int | None = None) -> dict:
    required = []
    low = task_description.lower()
    if 'code' in low or 'coding' in low:
        required.append('code')
    if 'fast' in low or 'quick' in low:
        required.append('fast-response')
    model = recommend_model(task_description, {
        'required_tags': required,
        'min_context_window': context_window_needed or 0,
    })
    return {
        'model_id': model['model_id'],
        'provider': model['provider'],
        'routing_tags': model.get('routing_tags', []),
        'reasoning': f"Matched task '{task_description}' against routing tags",
    }


def main():
    parser = argparse.ArgumentParser(description='OpenClaw model router')
    parser.add_argument('task_description')
    parser.add_argument('--context-window-needed', type=int)
    args = parser.parse_args()
    print(get_recommended_model(args.task_description, args.context_window_needed))


if __name__ == '__main__':
    main()
