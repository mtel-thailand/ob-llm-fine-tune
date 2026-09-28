#!/usr/bin/env python3
"""Train a local LoRA domain adapter from reviewed Chat Messages JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# This repository uses a src/ layout.  Adding it explicitly makes the script
# runnable through uv even when another project's virtual environment is
# currently active and this project has not been installed as a package.
PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from obk_llm_digests.sft_data import dataset_sha256, load_sft_records


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a review-only One Bangkok LoRA adapter")
    parser.add_argument("--dataset", required=True, help="Output from obk-llm-digests build-sft")
    parser.add_argument("--base-model", default="Qwen/Qwen3-1.7B")
    parser.add_argument("--output", required=True)
    parser.add_argument("--epochs", type=float, default=3)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--quantization", choices=("none", "4bit"), default="none",
                        help="4bit QLoRA requires NVIDIA CUDA; use none on Apple Silicon")
    parser.add_argument("--resume-from-checkpoint")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def tokenize_example(tokenizer, messages: list[dict], max_length: int) -> dict:
    prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    full_ids = tokenizer(full, add_special_tokens=False, truncation=True, max_length=max_length)["input_ids"]
    if len(full_ids) <= len(prompt_ids):
        raise ValueError("answer was removed by max-length; increase --max-length or shorten the record")
    return {"input_ids": full_ids, "attention_mask": [1] * len(full_ids),
            "labels": [-100] * min(len(prompt_ids), len(full_ids)) + full_ids[len(prompt_ids):]}


class CompletionCollator:
    def __init__(self, tokenizer): self.tokenizer = tokenizer

    def __call__(self, features):
        import torch
        labels = [item.pop("labels") for item in features]
        batch = self.tokenizer.pad(features, padding=True, return_tensors="pt")
        width = batch["input_ids"].shape[1]
        batch["labels"] = torch.tensor([label + [-100] * (width - len(label)) for label in labels], dtype=torch.long)
        return batch


def main() -> None:
    args = arguments()
    if args.epochs <= 0 or args.learning_rate <= 0 or args.batch_size < 1 or args.gradient_accumulation < 1 or args.max_length < 128:
        raise ValueError("invalid training numeric argument")
    records = load_sft_records(args.dataset)
    if args.dry_run:
        print(json.dumps({"valid_records": len(records), "dataset_sha256": dataset_sha256(args.dataset)}, indent=2))
        return
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer, TrainingArguments
    except ImportError as error:
        raise SystemExit("Missing dependencies. Run: python -m pip install -e '.[training]'") from error
    if args.quantization == "4bit" and not torch.cuda.is_available():
        raise SystemExit("--quantization 4bit requires NVIDIA CUDA. Use --quantization none on Apple Silicon.")
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=False)
    tokenizer.pad_token = tokenizer.pad_token or tokenizer.eos_token
    tokenizer.padding_side = "right"
    dataset = Dataset.from_list([tokenize_example(tokenizer, item["messages"], args.max_length) for item in records])
    model_args = {"trust_remote_code": False}
    if torch.cuda.is_available(): model_args["torch_dtype"] = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    if args.quantization == "4bit":
        model_args["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(args.base_model, **model_args)
    model.config.use_cache = False
    if args.quantization == "4bit": model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
                          bias="none", task_type="CAUSAL_LM", target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    model.print_trainable_parameters()
    output = Path(args.output)
    train_args = TrainingArguments(output_dir=str(output), num_train_epochs=args.epochs, learning_rate=args.learning_rate,
        per_device_train_batch_size=args.batch_size, gradient_accumulation_steps=args.gradient_accumulation,
        logging_steps=5, save_strategy="epoch", save_total_limit=2, report_to=[],
        fp16=torch.cuda.is_available() and not torch.cuda.is_bf16_supported(), bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported())
    trainer = Trainer(model=model, args=train_args, train_dataset=dataset, data_collator=CompletionCollator(tokenizer))
    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    trainer.save_model(str(output)); tokenizer.save_pretrained(output)
    (output / "training-manifest.json").write_text(json.dumps({"format": "one-bangkok-lora-v1", "created_at": datetime.now(UTC).isoformat(),
        "base_model": args.base_model, "dataset_sha256": dataset_sha256(args.dataset), "examples": len(records), "quantization": args.quantization,
        "lora": {"r": args.lora_r, "alpha": args.lora_alpha, "dropout": args.lora_dropout}}, indent=2) + "\n", encoding="utf-8")
    print(f"LoRA adapter complete: {output}")


if __name__ == "__main__":
    try: main()
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr); raise SystemExit(2) from error
