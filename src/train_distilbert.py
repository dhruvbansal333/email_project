"""
Phase 4, Step 4.2 — Fine-tune DistilBERT for commitment extraction as
token classification (BIO tagging over B/I-MADE, B/I-REQUESTED, O).

Trained on CPU in this environment — kept small (few epochs, short
max_length) to fit the compute budget. Documented as a real constraint
in the report: a GPU would allow more epochs / larger batches for
likely-better results, but this proves the approach and gives real,
comparable numbers against the Step 4.1 baseline.
"""

import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForTokenClassification,
    TrainingArguments,
    Trainer,
    DataCollatorForTokenClassification,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "gold_set" / "v1"
MODEL_NAME = "distilbert-base-uncased"
MAX_LENGTH = 256
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "models" / "distilbert_commitment"

LABELS = ["O", "B-MADE", "I-MADE", "B-REQUESTED", "I-REQUESTED"]
LABEL2ID = {l: i for i, l in enumerate(LABELS)}
ID2LABEL = {i: l for i, l in enumerate(LABELS)}


class BIODataset(Dataset):
    def __init__(self, examples, tokenizer):
        self.examples = examples
        self.tokenizer = tokenizer

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        ex = self.examples[idx]
        tokenized = self.tokenizer(
            ex["tokens"],
            is_split_into_words=True,
            truncation=True,
            max_length=MAX_LENGTH,
        )
        word_ids = tokenized.word_ids()
        labels = []
        prev_word_id = None
        for wid in word_ids:
            if wid is None:
                labels.append(-100)  # special tokens ignored in loss
            elif wid != prev_word_id:
                labels.append(LABEL2ID[ex["tags"][wid]])
            else:
                # subword continuation — inherit I- version of the tag if
                # the word-level tag was B-, else copy as-is
                tag = ex["tags"][wid]
                if tag.startswith("B-"):
                    tag = "I-" + tag[2:]
                labels.append(LABEL2ID[tag])
            prev_word_id = wid

        tokenized["labels"] = labels
        return {k: torch.tensor(v) for k, v in tokenized.items()}


def compute_metrics(eval_pred):
    predictions, labels = eval_pred
    predictions = np.argmax(predictions, axis=2)

    true_labels, true_preds = [], []
    for pred_row, label_row in zip(predictions, labels):
        for p, l in zip(pred_row, label_row):
            if l == -100:
                continue
            true_labels.append(l)
            true_preds.append(p)

    true_labels = np.array(true_labels)
    true_preds = np.array(true_preds)

    # Token-level metrics on non-O labels only (span-detection quality)
    non_o_mask = true_labels != LABEL2ID["O"]
    if non_o_mask.sum() == 0:
        span_acc = 0.0
    else:
        span_acc = (true_preds[non_o_mask] == true_labels[non_o_mask]).mean()

    overall_acc = (true_preds == true_labels).mean()

    # Precision/recall on "is this token part of ANY commitment" (binary)
    pred_is_commit = true_preds != LABEL2ID["O"]
    gold_is_commit = true_labels != LABEL2ID["O"]
    tp = (pred_is_commit & gold_is_commit).sum()
    fp = (pred_is_commit & ~gold_is_commit).sum()
    fn = (~pred_is_commit & gold_is_commit).sum()
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "token_accuracy": overall_acc,
        "commitment_token_precision": precision,
        "commitment_token_recall": recall,
        "commitment_token_f1": f1,
        "tag_accuracy_on_commitment_tokens": span_acc,
    }


def main():
    print("Loading data...")
    train_examples = json.load(open(DATA_DIR / "bio_train.json"))
    val_examples = json.load(open(DATA_DIR / "bio_val.json"))
    print(f"  train: {len(train_examples)}  val: {len(val_examples)}")

    print(f"Loading tokenizer/model: {MODEL_NAME}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForTokenClassification.from_pretrained(
        MODEL_NAME, num_labels=len(LABELS), id2label=ID2LABEL, label2id=LABEL2ID
    )

    train_dataset = BIODataset(train_examples, tokenizer)
    val_dataset = BIODataset(val_examples, tokenizer)
    collator = DataCollatorForTokenClassification(tokenizer)

    args = TrainingArguments(
        output_dir=str(OUTPUT_DIR),
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        learning_rate=3e-5,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        num_train_epochs=4,
        weight_decay=0.01,
        logging_steps=20,
        load_best_model_at_end=True,
        metric_for_best_model="commitment_token_f1",
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=collator,
        compute_metrics=compute_metrics,
    )

    print("Training...")
    trainer.train()

    print("\nFinal validation evaluation:")
    metrics = trainer.evaluate()
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    trainer.save_model(str(OUTPUT_DIR / "final"))
    tokenizer.save_pretrained(str(OUTPUT_DIR / "final"))

    with open(DATA_DIR / "distilbert_val_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nSaved model to {OUTPUT_DIR / 'final'}")
    print(f"Saved metrics to {DATA_DIR / 'distilbert_val_metrics.json'}")


if __name__ == "__main__":
    main()
