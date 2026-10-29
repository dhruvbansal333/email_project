"""Tests for src/ranking_eval.py. Run from the project root:  python -m pytest -q tests/test_ranking_eval.py"""
import csv
import json
import math
import random
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import ranking_eval as R  # noqa: E402

HAVE_DATA = R.VAL_FILE.exists() and R.TRAIN_FILE.exists()
needs_data = pytest.mark.skipif(not HAVE_DATA, reason="data/gold_set/v1/gold_val.json and gold_train.json not found")


# ------------------------------------------------------------------ sampling and safeguards
@needs_data
def test_sample_is_deterministic_unique_and_validation_only():
    val = R.load_json(R.VAL_FILE)
    a = [R.item_id(r) for r in R.pick_sample(val, 60, 42)]
    b = [R.item_id(r) for r in R.pick_sample(list(reversed(val)), 60, 42)]
    assert a == b and len(a) == len(set(a)) == 60            # independent of file order, no duplicates
    assert set(a) <= {R.item_id(r) for r in val}
    train_ids = {R.item_id(r) for r in R.load_json(R.TRAIN_FILE)}
    assert not (set(a) & train_ids)                          # nothing from the training split
    assert a != [R.item_id(r) for r in R.pick_sample(val, 60, 7)]   # different seed, different sample


def test_test_split_files_are_refused():
    for name in ("gold_test.json", "documents_test.json", "bio_test.json"):
        with pytest.raises(SystemExit):
            R.load_json(ROOT / "data" / "gold_set" / "v1" / name)
    with pytest.raises(SystemExit):
        R.make_sheet(val_file=ROOT / "data" / "gold_set" / "v1" / "gold_test.json")


def test_source_has_no_reference_to_the_test_file():
    code = Path(R.__file__).read_text(encoding="utf-8")
    assert "gold_test.json" not in code.replace('"gold_test.json"', "")  # only the guard's own wording may mention tests


@needs_data
def test_sheet_is_blind_and_never_overwrites_labels(tmp_path):
    sheet, manifest = R.make_sheet(eval_dir=tmp_path)
    rows = list(csv.DictReader(open(sheet, newline="", encoding="utf-8-sig")))
    assert len(rows) == 60 and list(rows[0].keys()) == R.SHEET_COLUMNS
    forbidden = {"confidence", "urgency_score", "score", "tier", "explanation", "sender", "recipient", "thread_id"}
    assert not forbidden & set(rows[0].keys())
    assert all(r["urgency_label"] == "" for r in rows)
    assert all("\n" not in v for r in rows for v in r.values())
    # a labelled sheet must survive a second make-sheet call
    rows[0]["urgency_label"] = "HIGH"
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=R.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(SystemExit):
        R.make_sheet(eval_dir=tmp_path)
    after = list(csv.DictReader(open(sheet, newline="", encoding="utf-8-sig")))
    assert after[0]["urgency_label"] == "HIGH"


@needs_data
def test_existing_annotation_files_are_not_modified(tmp_path):
    before = {p: R.sha256_file(p) for p in (R.VAL_FILE, R.TRAIN_FILE)}
    R.make_sheet(eval_dir=tmp_path)
    assert before == {p: R.sha256_file(p) for p in before}


# ------------------------------------------------------------------ metric maths
def test_average_ranks_handles_ties():
    assert R.average_ranks([10, 20, 20, 30]) == [1, 2.5, 2.5, 4]
    assert R.average_ranks([5, 5, 5]) == [2, 2, 2]


def test_perfect_and_reversed_ordering():
    labels = [2, 2, 1, 1, 0, 0, 0]
    perfect = [90, 80, 60, 50, 30, 20, 10]
    m = R.all_metrics(perfect, labels)
    assert m["spearman"] > 0.9 and m["ndcg_at_10"] == pytest.approx(1.0)
    assert m["pairwise_accuracy"] == 1.0 and m["r_precision_high"] == 1.0
    rev = R.all_metrics([-s for s in perfect], labels)
    assert rev["spearman"] < -0.9 and rev["pairwise_accuracy"] == 0.0 and rev["r_precision_high"] == 0.0
    assert rev["ndcg_at_10"] < 0.8


def test_everything_tied_gives_chance_level_not_a_perfect_score():
    labels = [2, 1, 0, 2, 1, 0, 0, 1]
    tied = [50.0] * len(labels)
    m = R.all_metrics(tied, labels)
    assert m["spearman"] is None                        # undefined, not 0 or 1
    assert m["pairwise_accuracy"] == pytest.approx(0.5)
    assert m["r_precision_high"] == pytest.approx(2 / 8)   # 2 HIGH among 8 -> expected share equals base rate
    assert 0 < m["ndcg_at_10"] < 1


def test_ndcg_tie_handling_equals_average_over_random_tie_breaks():
    scores = [9, 5, 5, 5, 1]
    labels = [2, 0, 2, 1, 0]
    expected = []
    for order in __import__("itertools").permutations([1, 2, 3]):
        ranked = [0, *order, 4]
        dcg = sum(labels[i] / math.log2(p + 2) for p, i in enumerate(ranked))
        ideal = sum(g / math.log2(p + 2) for p, g in enumerate(sorted(labels, reverse=True)))
        expected.append(dcg / ideal)
    assert R.ndcg_at_k(scores, labels, 5) == pytest.approx(sum(expected) / len(expected))


def test_r_precision_splits_boundary_ties_fairly():
    # two HIGH items; scorer puts 1 clear winner (HIGH) then a 3-way tie containing the other HIGH
    scores = [10, 5, 5, 5, 0]
    labels = [2, 2, 0, 0, 0]
    assert R.r_precision_high(scores, labels) == pytest.approx((1 + 1 / 3) / 2)


def test_pairwise_accuracy_counts_ties_as_half():
    acc, tied, total = R.pairwise_accuracy([1, 1], [2, 0])
    assert (acc, tied, total) == (0.5, 1.0, 1)


def test_matches_scipy_when_available():
    scipy_stats = pytest.importorskip("scipy.stats")
    rng = random.Random(3)
    for _ in range(25):
        n = rng.randint(12, 40)
        scores = [rng.choice([10, 20, 20, 30, 40, 55.5, 55.5, 70]) for _ in range(n)]
        labels = [rng.choice([0, 1, 2]) for _ in range(n)]
        if len(set(scores)) < 2 or len(set(labels)) < 2:
            continue
        assert R.spearman(scores, labels) == pytest.approx(scipy_stats.spearmanr(scores, labels)[0], abs=1e-9)


def test_bootstrap_is_reproducible_and_brackets_the_estimate():
    rng = random.Random(1)
    labels = [rng.choice([0, 1, 2]) for _ in range(60)]
    scores = [l * 30 + rng.random() * 40 for l in labels]
    a = R.bootstrap_ci(scores, labels, n_boot=300, seed=5)
    b = R.bootstrap_ci(scores, labels, n_boot=300, seed=5)
    assert a == b
    point = R.all_metrics(scores, labels)
    for k in ("spearman", "pairwise_accuracy"):
        assert a[k][0] <= point[k] <= a[k][1]


def test_random_baseline_is_near_chance():
    labels = [0] * 25 + [1] * 20 + [2] * 15
    b = R.random_baseline(labels, n_sims=300, seed=1)
    assert abs(b["spearman"]) < 0.05 and abs(b["pairwise_accuracy"] - 0.5) < 0.03


# ------------------------------------------------------------------ sheet validation
def _filled_sheet(tmp_path, labeller):
    sheet, manifest = R.make_sheet(eval_dir=tmp_path)
    rows = list(csv.DictReader(open(sheet, newline="", encoding="utf-8-sig")))
    for i, r in enumerate(rows):
        r["urgency_label"] = labeller(i, r)
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=R.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return sheet, json.loads(Path(manifest).read_text(encoding="utf-8"))


@needs_data
def test_unlabelled_or_invalid_rows_are_reported_clearly(tmp_path):
    sheet, manifest = _filled_sheet(tmp_path, lambda i, r: "" if i < 3 else "low")
    with pytest.raises(SystemExit) as e:
        R.read_sheet(sheet, manifest)
    assert "3 rows have no urgency_label" in str(e.value)
    (tmp_path / "second").mkdir()
    sheet, manifest = _filled_sheet(tmp_path / "second", lambda i, r: "urgent!!" if i == 0 else "LOW")
    with pytest.raises(SystemExit) as e:
        R.read_sheet(sheet, manifest)
    assert "invalid label" in str(e.value)


@needs_data
def test_labels_accept_case_and_abbreviations(tmp_path):
    cycle = ["h", "Medium", "L", " high ", "M", "LOW"]
    sheet, manifest = _filled_sheet(tmp_path, lambda i, r: cycle[i % 6])
    rows, labels = R.read_sheet(sheet, manifest)
    assert set(labels.values()) == {"HIGH", "MEDIUM", "LOW"}


@needs_data
def test_reordered_or_edited_sheet_is_rejected(tmp_path):
    sheet, manifest = _filled_sheet(tmp_path, lambda i, r: "LOW")
    rows = list(csv.DictReader(open(sheet, newline="", encoding="utf-8-sig")))
    rows[0], rows[1] = rows[1], rows[0]
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=R.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(SystemExit):
        R.read_sheet(sheet, manifest)


# ------------------------------------------------------------------ end to end with the real scorer
@needs_data
def test_end_to_end_with_real_scorer_on_synthetic_labels(tmp_path):
    """SYNTHETIC labels derived from the scorer itself, used only to prove the pipeline runs and that the metrics
    reach ~1 when labels equal the scorer's own tiers. These are NOT evaluation results."""
    val = R.load_json(R.VAL_FILE)
    scored = R.score_val_items(val, R.load_json(R.TRAIN_FILE))
    sheet, manifest = _filled_sheet(tmp_path, lambda i, r: "LOW")   # placeholder, rewritten below
    rows = list(csv.DictReader(open(sheet, newline="", encoding="utf-8-sig")))
    for r in rows:
        r["urgency_label"] = R.tier_of(scored[r["item_id"]]["score"])
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=R.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    res = R.evaluate(eval_dir=tmp_path, n_boot=200)
    assert res["n"] == 60 and res["scorer"]["spearman"] > 0.9 and res["scorer"]["pairwise_accuracy"] > 0.95
    assert (tmp_path / R.RESULTS_NAME).exists()
    assert sum(sum(v.values()) for v in res["confusion_human_rows_vs_scorer_tier_cols"].values()) == 60
    assert len(res["largest_disagreements"]) == 8
    R.print_report(res)


def test_tier_thresholds_match_the_scorer_source():
    src = (ROOT / "src" / "rank_score.py").read_text(encoding="utf-8")
    m = re.search(r'"HIGH" if score >= (\d+) else \("MEDIUM" if score >= (\d+) else "LOW"\)', src)
    assert m and (int(m.group(1)), int(m.group(2))) == (R.TIER_HIGH, R.TIER_MEDIUM)


# ------------------------------------------------------------------ paired comparison (exploratory)
def test_paired_difference_is_zero_for_identical_orderings():
    labels = [0, 1, 2, 1, 0, 2, 1, 0] * 6
    scores = [l * 10 + (i % 5) for i, l in enumerate(labels)]
    out = R.paired_difference_ci(scores, list(scores), labels, n_boot=200, seed=1)
    for k, v in out.items():
        assert v["estimate"] == 0 and v["ci95"] == [0, 0] and v["ci_excludes_zero"] is False


def test_paired_difference_detects_a_clearly_better_ordering_and_is_reproducible():
    rng = random.Random(4)
    labels = [rng.choice([0, 1, 2]) for _ in range(80)]
    good = [l * 30 + rng.random() * 20 for l in labels]
    noise = [rng.random() * 100 for _ in labels]
    a = R.paired_difference_ci(good, noise, labels, n_boot=300, seed=2)
    assert a == R.paired_difference_ci(good, noise, labels, n_boot=300, seed=2)
    assert a["spearman"]["estimate"] > 0.5 and a["spearman"]["ci_excludes_zero"] is True
    rev = R.paired_difference_ci(noise, good, labels, n_boot=300, seed=2)
    assert rev["spearman"]["estimate"] < -0.5 and rev["spearman"]["ci95"][1] < 0


@needs_data
def test_evaluate_reports_the_paired_comparison(tmp_path):
    val = R.load_json(R.VAL_FILE)
    scored = R.score_val_items(val, R.load_json(R.TRAIN_FILE))
    sheet, manifest = _filled_sheet(tmp_path, lambda i, r: "LOW")
    rows = list(csv.DictReader(open(sheet, newline="", encoding="utf-8-sig")))
    for r in rows:
        r["urgency_label"] = R.tier_of(scored[r["item_id"]]["score"])
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=R.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    res = R.evaluate(eval_dir=tmp_path, n_boot=150)
    assert set(res["exploratory_paired_difference_scorer_minus_deadline_only"]) == {
        "spearman", "ndcg_at_10", "pairwise_accuracy", "r_precision_high"}