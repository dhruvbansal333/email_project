"""Phase 6 addendum: ranking evaluation against independent human urgency labels.

Why this exists
---------------
The gold set has no urgency labels (its HIGH/MEDIUM/LOW `confidence` field is extraction confidence, and the scorer
uses it as an input), so ranking quality cannot be measured from existing annotations without circularity. This tool:

  make-sheet : picks N validation commitments (deterministic, seed 42) and writes a BLIND labelling sheet. The sheet
               never shows the scorer's score/tier/explanation or the `confidence` field.
  evaluate   : reads the filled sheet, scores the same commitments with the real scorer (src/rank_features.py,
               src/rank_score.py), and reports Spearman, tie-aware NDCG@10, pairwise accuracy, tie-aware HIGH
               R-precision, a tier confusion matrix, simple baselines and bootstrap 95% confidence intervals.

Safeguards
----------
* Only data/gold_set/v1/gold_val.json is read for evaluation items. The test split is never opened; any file path
  containing "test" is rejected.
* Existing annotation files are never modified. New labels live in data/ranking_eval/.
* Standard library only.

Usage (from the project root):
    python -m src.ranking_eval make-sheet            # once; then fill the urgency_label column
    python -m src.ranking_eval evaluate
"""
import argparse
import csv
import hashlib
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

try:  # run as `python -m src.ranking_eval` from the project root
    from src.rank_features import build_sender_frequency_table, compute_features
    from src.rank_score import score_commitment
except ImportError:  # run from inside src/ or with src on the path
    from rank_features import build_sender_frequency_table, compute_features
    from rank_score import score_commitment

ROOT = Path(__file__).resolve().parent.parent
GOLD_DIR = ROOT / "data" / "gold_set" / "v1"
EVAL_DIR = ROOT / "data" / "ranking_eval"
VAL_FILE = GOLD_DIR / "gold_val.json"
TRAIN_FILE = GOLD_DIR / "gold_train.json"   # used ONLY to build the sender-frequency table, as in Phase 5

SHEET_NAME = "urgency_sheet_val.csv"
MANIFEST_NAME = "sample_manifest.json"
RESULTS_NAME = "ranking_eval_results.json"

DEFAULT_N = 60
DEFAULT_SEED = 42
LABELS = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
ALIASES = {"L": "LOW", "M": "MEDIUM", "MED": "MEDIUM", "H": "HIGH"}
SHEET_COLUMNS = ["item_id", "subject", "commitment_text", "direction", "deadline_text", "urgency_label", "note"]

# Same thresholds rank_score.generate_explanation uses for its HIGH / MEDIUM / LOW tag (checked by a test).
TIER_HIGH, TIER_MEDIUM = 65, 40


# ------------------------------------------------------------------ data helpers
def _refuse_test_path(path):
    if "test" in Path(path).name.lower():
        raise SystemExit(f"Refusing to read {path}: the held-out test split must not be used here.")


def item_id(row):
    """Stable id for a validation commitment (gold_val.json has no id column; this was checked to be unique)."""
    return hashlib.sha1(f"{row['thread_id']}|{row['commitment_text']}".encode("utf-8")).hexdigest()[:10]


def load_json(path):
    _refuse_test_path(path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pick_sample(val_rows, n, seed):
    """Deterministic and independent of the Python version: order by SHA-256(seed|item_id), take the first n."""
    ids = [item_id(r) for r in val_rows]
    if len(set(ids)) != len(ids):
        raise SystemExit("Validation item ids are not unique; cannot build a reliable sample.")
    order = sorted(range(len(val_rows)), key=lambda i: hashlib.sha256(f"{seed}|{ids[i]}".encode()).hexdigest())
    return [val_rows[i] for i in order[:n]]


def clean(v):
    """Display form for the sheet: blank for missing values and single-line text (line breaks hurt readability in Excel).
    Ids are computed from the original text, so this never affects item identity."""
    return "" if v in (None, "None") else " ".join(str(v).split())


# ------------------------------------------------------------------ make-sheet
def make_sheet(n=DEFAULT_N, seed=DEFAULT_SEED, force=False, val_file=VAL_FILE, eval_dir=EVAL_DIR):
    val = load_json(val_file)
    n = min(n, len(val))
    eval_dir = Path(eval_dir)
    eval_dir.mkdir(parents=True, exist_ok=True)
    sheet, manifest = eval_dir / SHEET_NAME, eval_dir / MANIFEST_NAME
    if sheet.exists() and not force:
        raise SystemExit(f"{sheet} already exists and may contain your labels. Not overwriting (use --force to replace).")
    sample = pick_sample(val, n, seed)
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig so Excel opens it correctly
        w = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        w.writeheader()
        for r in sample:
            w.writerow({
                "item_id": item_id(r), "subject": clean(r["subject"]), "commitment_text": clean(r["commitment_text"]),
                "direction": clean(r["direction"]), "deadline_text": clean(r["deadline_text"]),
                "urgency_label": "", "note": "",
            })
    manifest.write_text(json.dumps({
        "split": "validation", "seed": seed, "n": n, "selection": "sort by sha256(seed|item_id), take first n",
        "source_file": "data/gold_set/v1/gold_val.json", "source_sha256": sha256_file(val_file),
        "item_ids": [item_id(r) for r in sample],
    }, indent=2), encoding="utf-8")
    return sheet, manifest


# ------------------------------------------------------------------ metrics (all tie-aware)
def average_ranks(values):
    """1-based ascending ranks; ties get the mean of the ranks they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def pearson(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return cov / math.sqrt(va * vb)


def spearman(scores, labels):
    return pearson(average_ranks(scores), average_ranks(labels))


def pairwise_accuracy(scores, labels):
    """Over all pairs with different human labels: 1 if the scorer orders them the same way, 0.5 if it ties them."""
    correct = tied = total = 0
    n = len(scores)
    for i in range(n):
        for j in range(n):
            if labels[i] > labels[j]:
                total += 1
                if scores[i] > scores[j]:
                    correct += 1
                elif scores[i] == scores[j]:
                    correct += 0.5
                    tied += 1
    if total == 0:
        return None, None, 0
    return correct / total, tied / total, total


def _groups_desc(scores):
    """Indices grouped by equal score, highest score first."""
    by = {}
    for i, s in enumerate(scores):
        by.setdefault(s, []).append(i)
    return [by[s] for s in sorted(by, reverse=True)]


def ndcg_at_k(scores, labels, k=10):
    """Linear-gain NDCG@k with expected value over random tie-breaking: tied items share the positions they span."""
    k = min(k, len(scores))
    dcg, pos = 0.0, 1
    for grp in _groups_desc(scores):
        if pos > k:
            break
        last = min(pos + len(grp) - 1, k)
        disc = sum(1 / math.log2(p + 1) for p in range(pos, last + 1))
        dcg += (sum(labels[i] for i in grp) / len(grp)) * disc
        pos += len(grp)
    ideal = sorted(labels, reverse=True)[:k]
    idcg = sum(g / math.log2(p + 2) for p, g in enumerate(ideal))
    return None if idcg == 0 else dcg / idcg


def r_precision_high(scores, labels):
    """Of the scorer's top-R (R = number of human HIGH items), the expected share that is HIGH (ties split fairly)."""
    high = LABELS["HIGH"]
    r = sum(1 for x in labels if x == high)
    if r == 0:
        return None
    taken, hits = 0, 0.0
    for grp in _groups_desc(scores):
        room = r - taken
        if room <= 0:
            break
        share = min(1.0, room / len(grp))
        hits += share * sum(1 for i in grp if labels[i] == high)
        taken += min(len(grp), room)
    return hits / r


def all_metrics(scores, labels):
    acc, tied, _ = pairwise_accuracy(scores, labels)
    return {"spearman": spearman(scores, labels), "ndcg_at_10": ndcg_at_k(scores, labels, 10),
            "pairwise_accuracy": acc, "r_precision_high": r_precision_high(scores, labels)}


def bootstrap_ci(scores, labels, n_boot=2000, seed=DEFAULT_SEED):
    rng = random.Random(seed)
    n = len(scores)
    draws = {k: [] for k in ("spearman", "ndcg_at_10", "pairwise_accuracy", "r_precision_high")}
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        m = all_metrics([scores[i] for i in idx], [labels[i] for i in idx])
        for k, v in m.items():
            if v is not None:
                draws[k].append(v)
    out = {}
    for k, v in draws.items():
        v.sort()
        out[k] = None if len(v) < 20 else [v[int(0.025 * (len(v) - 1))], v[int(0.975 * (len(v) - 1))]]
    return out


def paired_difference_ci(scores_a, scores_b, labels, n_boot=2000, seed=DEFAULT_SEED):
    """Paired bootstrap of metric(A) - metric(B): the SAME resampled items are used for both orderings, so the
    interval reflects whether A really differs from B on this sample (exploratory; with n=60 it is wide)."""
    rng = random.Random(seed)
    n = len(labels)
    keys = ("spearman", "ndcg_at_10", "pairwise_accuracy", "r_precision_high")
    diffs = {k: [] for k in keys}
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        la = [labels[i] for i in idx]
        ma = all_metrics([scores_a[i] for i in idx], la)
        mb = all_metrics([scores_b[i] for i in idx], la)
        for k in keys:
            if ma[k] is not None and mb[k] is not None:
                diffs[k].append(ma[k] - mb[k])
    point_a, point_b = all_metrics(scores_a, labels), all_metrics(scores_b, labels)
    out = {}
    for k in keys:
        d = sorted(diffs[k])
        est = None if point_a[k] is None or point_b[k] is None else point_a[k] - point_b[k]
        ci = None if len(d) < 20 else [d[int(0.025 * (len(d) - 1))], d[int(0.975 * (len(d) - 1))]]
        out[k] = {"estimate": est, "ci95": ci, "ci_excludes_zero": None if ci is None else (ci[0] > 0 or ci[1] < 0)}
    return out


def random_baseline(labels, n_sims=500, seed=DEFAULT_SEED):
    rng = random.Random(seed)
    acc = {k: [] for k in ("spearman", "ndcg_at_10", "pairwise_accuracy", "r_precision_high")}
    for _ in range(n_sims):
        m = all_metrics([rng.random() for _ in labels], labels)
        for k, v in m.items():
            if v is not None:
                acc[k].append(v)
    return {k: (sum(v) / len(v) if v else None) for k, v in acc.items()}


def tier_of(score):
    return "HIGH" if score >= TIER_HIGH else ("MEDIUM" if score >= TIER_MEDIUM else "LOW")


# ------------------------------------------------------------------ evaluate
def read_sheet(path, manifest=None):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    if manifest is not None and [r["item_id"] for r in rows] != manifest["item_ids"]:
        raise SystemExit("The sheet's item_id column does not match sample_manifest.json (rows added, removed or "
                         "reordered?). Restore the original sheet and only fill in urgency_label.")
    missing, bad, labels = [], [], {}
    for r in rows:
        raw = (r.get("urgency_label") or "").strip().upper()
        raw = ALIASES.get(raw, raw)
        if raw == "":
            missing.append(r["item_id"])
        elif raw not in LABELS:
            bad.append((r["item_id"], r["urgency_label"]))
        else:
            labels[r["item_id"]] = raw
    if missing or bad:
        msg = []
        if missing:
            msg.append(f"{len(missing)} rows have no urgency_label yet (e.g. {missing[:5]}).")
        if bad:
            msg.append(f"{len(bad)} rows have an invalid label (use HIGH, MEDIUM or LOW): {bad[:5]}")
        raise SystemExit(" ".join(msg))
    return rows, labels


def score_val_items(val_rows, train_rows):
    """Score with the real Phase 5 code. Sender-frequency table = train + val, exactly as in Phase 5 / production."""
    table = build_sender_frequency_table(train_rows + val_rows)
    max_freq = max(table.values()) if table else 1
    out = {}
    for r in val_rows:
        feats = compute_features(r, table, max_freq)
        out[item_id(r)] = {"score": score_commitment(feats), "deadline_urgency": feats["deadline_urgency"]}
    return out


def evaluate(sheet_path=None, eval_dir=EVAL_DIR, val_file=VAL_FILE, train_file=TRAIN_FILE, n_boot=2000):
    eval_dir = Path(eval_dir)
    sheet_path = Path(sheet_path) if sheet_path else eval_dir / SHEET_NAME
    manifest = json.loads((eval_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    val = load_json(val_file)
    train = load_json(train_file)
    warnings = []
    if sha256_file(val_file) != manifest["source_sha256"]:
        warnings.append("gold_val.json has changed since the sample was drawn.")
    rows, human = read_sheet(sheet_path, manifest)
    by_id = {item_id(r): r for r in val}
    scored = score_val_items(val, train)
    ids = [r["item_id"] for r in rows]
    scores = [scored[i]["score"] for i in ids]
    labels = [LABELS[human[i]] for i in ids]
    counts = Counter(human[i] for i in ids)
    for name in LABELS:
        if counts[name] < 5:
            warnings.append(f"Only {counts[name]} items labelled {name}: metrics involving that class are unreliable.")

    res = {
        "n": len(ids), "label_counts": dict(counts), "distinct_scorer_scores": len(set(scores)),
        "scorer": all_metrics(scores, labels), "scorer_ci95": bootstrap_ci(scores, labels, n_boot),
        "pairwise_tied_fraction": pairwise_accuracy(scores, labels)[1], "pairs_compared": pairwise_accuracy(scores, labels)[2],
        "baseline_random_expected": random_baseline(labels),
        "baseline_deadline_only": all_metrics([scored[i]["deadline_urgency"] for i in ids], labels),
        "exploratory_paired_difference_scorer_minus_deadline_only": paired_difference_ci(
            scores, [scored[i]["deadline_urgency"] for i in ids], labels, n_boot),
        "warnings": warnings,
    }
    conf = {h: {t: 0 for t in LABELS} for h in LABELS}
    for i in ids:
        conf[human[i]][tier_of(scored[i]["score"])] += 1
    res["confusion_human_rows_vs_scorer_tier_cols"] = conf

    sp = [x / len(ids) for x in average_ranks(scores)]
    hp = [x / len(ids) for x in average_ranks(labels)]
    gaps = sorted(range(len(ids)), key=lambda k: -abs(sp[k] - hp[k]))[:8]
    res["largest_disagreements"] = [{
        "item_id": ids[k], "human": human[ids[k]], "scorer_score": scores[k], "scorer_tier": tier_of(scores[k]),
        "deadline_text": clean(by_id[ids[k]]["deadline_text"]), "commitment_text": by_id[ids[k]]["commitment_text"][:140],
    } for k in gaps]
    (eval_dir / RESULTS_NAME).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


def _fmt(v):
    return "n/a" if v is None else f"{v:.3f}"


def _fmt_signed(v):
    return "n/a" if v is None else f"{v:+.3f}"


def print_report(res):
    print(f"\nRanking evaluation on {res['n']} validation commitments (human labels: {res['label_counts']})")
    print(f"Scorer produced {res['distinct_scorer_scores']} distinct scores for {res['n']} items "
          f"({res['pairwise_tied_fraction']:.0%} of compared pairs were tied by the scorer).\n")
    print(f"{'metric':<22}{'scorer':>9}   {'95% bootstrap CI':<20}{'deadline-only':>14}{'random (exp.)':>15}")
    for key, label in (("spearman", "Spearman rho"), ("ndcg_at_10", "NDCG@10"), ("pairwise_accuracy", "Pairwise accuracy"),
                       ("r_precision_high", "R-precision (HIGH)")):
        ci = res["scorer_ci95"][key]
        cis = "n/a" if ci is None else f"[{ci[0]:.3f}, {ci[1]:.3f}]"
        print(f"{label:<22}{_fmt(res['scorer'][key]):>9}   {cis:<20}{_fmt(res['baseline_deadline_only'][key]):>14}"
              f"{_fmt(res['baseline_random_expected'][key]):>15}")
    pd_ = res.get("exploratory_paired_difference_scorer_minus_deadline_only")
    if pd_:
        print("\nExploratory paired comparison, scorer minus deadline-only (same resampled items; not a pre-planned test):")
        for key, label in (("spearman", "Spearman rho"), ("ndcg_at_10", "NDCG@10"), ("pairwise_accuracy", "Pairwise accuracy"),
                           ("r_precision_high", "R-precision (HIGH)")):
            d = pd_[key]
            ci = "n/a" if d["ci95"] is None else f"[{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]"
            verdict = "n/a" if d["ci_excludes_zero"] is None else ("CI excludes 0" if d["ci_excludes_zero"] else "CI includes 0")
            print(f"  {label:<22}{_fmt_signed(d['estimate']):>8}   95% CI {ci:<20} {verdict}")
    print("\nConfusion (rows = human label, columns = scorer tier at thresholds 65/40):")
    print(f"{'':<8}" + "".join(f"{t:>8}" for t in LABELS))
    for h, row in res["confusion_human_rows_vs_scorer_tier_cols"].items():
        print(f"{h:<8}" + "".join(f"{row[t]:>8}" for t in LABELS))
    print("\nLargest disagreements (for error analysis):")
    for d in res["largest_disagreements"]:
        print(f"  human={d['human']:<6} scorer={d['scorer_score']:>5} ({d['scorer_tier']:<6}) deadline='{d['deadline_text']}' | {d['commitment_text']}")
    for w in res["warnings"]:
        print("WARNING:", w)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make-sheet")
    m.add_argument("--n", type=int, default=DEFAULT_N)
    m.add_argument("--seed", type=int, default=DEFAULT_SEED)
    m.add_argument("--force", action="store_true")
    e = sub.add_parser("evaluate")
    e.add_argument("--bootstrap", type=int, default=2000)
    args = p.parse_args(argv)
    if args.cmd == "make-sheet":
        sheet, manifest = make_sheet(args.n, args.seed, args.force)
        print(f"Wrote {sheet}\nWrote {manifest}\nFill the urgency_label column with HIGH, MEDIUM or LOW, then run: "
              f"python -m src.ranking_eval evaluate")
    else:
        print_report(evaluate(n_boot=args.bootstrap))


if __name__ == "__main__":
    sys.exit(main())