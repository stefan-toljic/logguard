import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import receiver  # noqa: E402


def test_alert_latency_and_storage():
    db = receiver.open_db(":memory:")
    msg = {"device_id": "lg-esp-poc1-01", "ts_us": 1_000_000, "time_synced": True,
           "class": "chainsaw", "score": 0.91, "score_int8": 105, "windows": 3, "rssi": -60}
    row = receiver.store(db, "logguard/alerts/lg-esp-poc1-01", json.dumps(msg), recv_us=1_250_000)
    assert row["latency_ms"] == 250
    assert db.execute("SELECT count(*), max(score) FROM alerts").fetchone() == (1, 0.91)
    assert "end-to-end=250 ms" in receiver.describe("logguard/alerts/x", row)


def test_unsynced_clock_has_no_latency():
    db = receiver.open_db(":memory:")
    msg = {"device_id": "d", "ts_us": 5, "time_synced": False, "score": 0.9, "windows": 3, "rssi": 0}
    row = receiver.store(db, "logguard/alerts/d", json.dumps(msg), recv_us=10)
    assert row["latency_ms"] is None


def test_status_and_unknown_topics():
    db = receiver.open_db(":memory:")
    receiver.store(db, "logguard/status/d", json.dumps({"device_id": "d", "uptime_s": 60}))
    assert db.execute("SELECT count(*) FROM status").fetchone() == (1,)
    assert receiver.store(db, "other/topic", "{}") is None
