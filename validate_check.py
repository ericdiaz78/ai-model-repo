#!/usr/bin/env python3
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
schema = json.load(open(ROOT / "schema.json"))
models = json.load(open(ROOT / "models.json"))
errors = []
for m in models:
    for prop in schema["items"]["required"]:
        if prop not in m:
            errors.append(f"{m.get('model_id','?')} missing required field: {prop}")
if errors:
    print("VALIDATION FAILED:")
    for e in errors: print(" ", e)
    sys.exit(1)
else:
    print(f"OK — {len(models)} models pass schema check (required fields present)")
    shelf_active = [m for m in models if m.get("_meta",{}).get("shelf") == "active"]
    shelf_discovery = [m for m in models if m.get("_meta",{}).get("shelf") == "discovery"]
    print(f"  Active: {len(shelf_active)} | Discovery: {len(shelf_discovery)}")
