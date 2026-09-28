#!/usr/bin/env python3
"""Merge a verified One Bangkok LoRA adapter into its base Transformers model."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--base-model", default="Qwen/Qwen3-1.7B")
parser.add_argument("--adapter", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
try:
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
except ImportError as error:
    raise SystemExit("Missing dependencies. Run: python -m pip install -e '.[training]'") from error
base = AutoModelForCausalLM.from_pretrained(args.base_model, trust_remote_code=False)
PeftModel.from_pretrained(base, args.adapter).merge_and_unload().save_pretrained(Path(args.output), safe_serialization=True)
AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=False).save_pretrained(Path(args.output))
print(f"merged model complete: {args.output}")
