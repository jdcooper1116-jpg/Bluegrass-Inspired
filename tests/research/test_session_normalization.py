from bluegrass.research.baseline import baseline_packet_summary


def test_baseline_summary_sessions_are_normalized() -> None:
    summary = baseline_packet_summary()

    assert summary["sessions"] == ["Midday", "Evening", "Night"]
    assert all("|" not in session for session in summary["sessions"])
