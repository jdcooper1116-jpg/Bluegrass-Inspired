from bluegrass.research.baseline import (
    baseline_packet_summary,
    filter_priority_shortlist,
    load_baseline_combinations,
    load_baseline_manifest,
    load_baseline_pairs,
    load_baseline_runs,
)


def test_baseline_counts_match_manifest() -> None:
    manifest = load_baseline_manifest()
    summary = manifest["summary"]

    assert len(load_baseline_runs()) == summary["total_runs"]
    assert len(load_baseline_pairs()) == summary["pair_rows"]
    assert len(load_baseline_combinations()) == summary["combination_rows"]


def test_pair_values_preserve_leading_zeroes() -> None:
    pairs = load_baseline_pairs()
    row = next(item for item in pairs if item["pair_value"] == "00")

    assert row["pair_value"] == "00"
    assert len(row["pair_value"]) == 2


def test_combo_values_preserve_leading_zeroes() -> None:
    combos = load_baseline_combinations()
    row = next(item for item in combos if item["combo_value"] == "000")

    assert row["combo_value"] == "000"
    assert len(row["combo_value"]) == 3


def test_summary_uses_manifest_values() -> None:
    summary = baseline_packet_summary()

    assert summary["total_runs"] == 47
    assert summary["pair_rows"] == 2630
    assert summary["combination_rows"] == 4880
    assert "Midday" in summary["sessions"]
    assert "Night" in summary["sessions"]


def test_priority_shortlist_is_sorted_descending() -> None:
    rows = filter_priority_shortlist(limit=5)

    assert len(rows) == 5
    scores = [float(row["baseline_priority_score"]) for row in rows]
    assert scores == sorted(scores, reverse=True)


def test_priority_shortlist_can_filter_by_session() -> None:
    rows = filter_priority_shortlist(session="Night", limit=10)

    assert rows
    assert all(row["session"] == "Night" for row in rows)
