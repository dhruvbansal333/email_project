"""
Phase 4, Step 4.2 — Trainable neural model (sandbox-compatible substitute
for pretrained DistilBERT fine-tuning).

IMPORTANT ENVIRONMENT NOTE: huggingface.co is not reachable from this
build sandbox's network allowlist (confirmed: 403 host_not_allowed), so
downloading pretrained DistilBERT weights isn't possible here.
`train_distilbert.py` in this same folder is the correct, complete
fine-tuning script — run it on a machine with Hugging Face Hub access
(e.g. locally, Colab, or a cloud GPU) to get the actual DistilBERT
numbers for the report.

This script trains a small BiLSTM token classifier FROM SCRATCH (random
embeddings, no pretrained weights, no internet dependency) on the same
BIO-tagged gold data, so we have a genuine trained-neural-model data
point to compare against the Step 4.1 rule-based baseline right now,
without waiting on external network access. It is not a substitute for
the DistilBERT result in the final report — it's a same-day fallback
that still answers "does a trainable model beat the rule-based
baseline on this data" using only what's available here.
"""

import json
from collections import Counter
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "gold_set" / "v1"
OUT_DIR = Path(__file__).resolve().parent.parent / "models" / "bilstm_commitment"

LABELS = ["O", "B-MADE", "I-MADE", "B-REQUESTED", "I-REQUESTED"]
LABEL2ID = {l: i for i, l in enumerate(LABELS)}
ID2LABEL = {i: l for i, l in enumerate(LABELS)}

EMBED_DIM = 100
HIDDEN_DIM = 128
BATCH_SIZE = 8
EPOCHS = 15
LR = 1e-3
MAX_LEN = 200


def build_vocab(train_examples, min_freq=2):
    counter = Counter()
    for ex in train_examples:
        counter.update(t.lower() for t in ex["tokens"])
    vocab = {"<PAD>": 0, "<UNK>": 1}
    for tok, freq in counter.items():
        if freq >= min_freq:
            vocab[tok] = len(vocab)
    return vocab


class BIODataset(Dataset):
    def __init__(self, examples, vocab):
        self.examples = examples
        self.vocab = vocab

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        ex = self.examples[idx]
        tokens = ex["tokens"][:MAX_LEN]
        tags = ex["tags"][:MAX_LEN]
        ids = [self.vocab.get(t.lower(), 1) for t in tokens]
        label_ids = [LABEL2ID[t] for t in tags]
        return torch.tensor(ids), torch.tensor(label_ids)


def collate(batch):
    ids, labels = zip(*batch)
    lengths = [len(x) for x in ids]
    max_len = max(lengths)
    padded_ids = torch.zeros(len(batch), max_len, dtype=torch.long)
    padded_labels = torch.full((len(batch), max_len), -100, dtype=torch.long)
    for i, (x, y) in enumerate(zip(ids, labels)):
        padded_ids[i, :len(x)] = x
        padded_labels[i, :len(y)] = y
    return padded_ids, padded_labels, torch.tensor(lengths)


class BiLSTMTagger(nn.Module):
    def __init__(self, vocab_size, embed_dim, hidden_dim, n_labels):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, embed_dim, padding_idx=0)
        self.lstm = nn.LSTM(embed_dim, hidden_dim, batch_first=True, bidirectional=True)
        self.dropout = nn.Dropout(0.3)
        self.classifier = nn.Linear(hidden_dim * 2, n_labels)

    def forward(self, x):
        emb = self.embedding(x)
        lstm_out, _ = self.lstm(emb)
        return self.classifier(self.dropout(lstm_out))


def evaluate(model, loader):
    model.eval()
    tp = fp = fn = 0
    correct_tags = total_commit_tokens = 0
    with torch.no_grad():
        for ids, labels, lengths in loader:
            logits = model(ids)
            preds = logits.argmax(dim=-1)
            mask = labels != -100

            pred_flat = preds[mask]
            gold_flat = labels[mask]

            pred_is_commit = pred_flat != LABEL2ID["O"]
            gold_is_commit = gold_flat != LABEL2ID["O"]

            tp += (pred_is_commit & gold_is_commit).sum().item()
            fp += (pred_is_commit & ~gold_is_commit).sum().item()
            fn += (~pred_is_commit & gold_is_commit).sum().item()

            commit_mask = gold_is_commit
            correct_tags += (pred_flat[commit_mask] == gold_flat[commit_mask]).sum().item()
            total_commit_tokens += commit_mask.sum().item()

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    tag_acc = correct_tags / total_commit_tokens if total_commit_tokens else 0.0

    return {
        "commitment_token_precision": precision,
        "commitment_token_recall": recall,
        "commitment_token_f1": f1,
        "tag_accuracy_on_commitment_tokens": tag_acc,
    }


def main():
    train_examples = json.load(open(DATA_DIR / "bio_train.json"))
    val_examples = json.load(open(DATA_DIR / "bio_val.json"))
    print(f"train: {len(train_examples)}  val: {len(val_examples)}")

    vocab = build_vocab(train_examples)
    print(f"Vocab size: {len(vocab)}")

    train_ds = BIODataset(train_examples, vocab)
    val_ds = BIODataset(val_examples, vocab)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, collate_fn=collate)

    model = BiLSTMTagger(len(vocab), EMBED_DIM, HIDDEN_DIM, len(LABELS))
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    loss_fn = nn.CrossEntropyLoss(ignore_index=-100)

    best_f1 = 0.0
    best_metrics = None
    for epoch in range(1, EPOCHS + 1):
        model.train()
        total_loss = 0.0
        for ids, labels, lengths in train_loader:
            optimizer.zero_grad()
            logits = model(ids)
            loss = loss_fn(logits.view(-1, len(LABELS)), labels.view(-1))
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        metrics = evaluate(model, val_loader)
        print(f"Epoch {epoch}/{EPOCHS} — loss={total_loss/len(train_loader):.4f} "
              f"val_f1={metrics['commitment_token_f1']:.3f} "
              f"val_P={metrics['commitment_token_precision']:.3f} "
              f"val_R={metrics['commitment_token_recall']:.3f}")

        if metrics["commitment_token_f1"] > best_f1:
            best_f1 = metrics["commitment_token_f1"]
            best_metrics = metrics
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), OUT_DIR / "best_model.pt")

    print(f"\nBest validation F1: {best_f1:.3f}")
    print(f"Best metrics: {best_metrics}")

    with open(DATA_DIR / "bilstm_val_metrics.json", "w") as f:
        json.dump(best_metrics, f, indent=2)
    with open(OUT_DIR / "vocab.json", "w") as f:
        json.dump(vocab, f)
    print(f"Saved best model + metrics to {OUT_DIR} and {DATA_DIR / 'bilstm_val_metrics.json'}")


if __name__ == "__main__":
    main()
