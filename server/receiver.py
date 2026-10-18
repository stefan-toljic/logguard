"""Receive LogGuard alerts and heartbeats over MQTT and log them to SQLite.

    python receiver.py --host localhost --user logguard --password ...

Prints the end-to-end latency of every alert (detection on the device to
arrival here), which is one of the measured values in the test protocol.
"""
import argparse
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts(
    id INTEGER PRIMARY KEY, device_id TEXT, ts_us INTEGER, time_synced INTEGER,
    recv_us INTEGER, latency_ms REAL, class TEXT, score REAL, score_int8 INTEGER,
    windows INTEGER, rssi INTEGER, raw TEXT);
CREATE TABLE IF NOT EXISTS status(
    id INTEGER PRIMARY KEY, device_id TEXT, recv_us INTEGER, uptime_s INTEGER,
    free_heap INTEGER, pending INTEGER, raw TEXT);
"""


def open_db(path):
    db = sqlite3.connect(path, check_same_thread=False)
    db.executescript(SCHEMA)
    return db


def store(db, topic, payload, recv_us=None):
    """Store one message; returns the row as a dict (or None if ignored)."""
    recv_us = recv_us if recv_us is not None else int(time.time() * 1e6)
    d = json.loads(payload)
    if topic.startswith("logguard/alerts/"):
        synced = bool(d.get("time_synced", True))
        latency = (recv_us - d["ts_us"]) / 1000 if synced else None
        row = dict(device_id=d["device_id"], ts_us=d["ts_us"], time_synced=int(synced),
                   recv_us=recv_us, latency_ms=latency, **{"class": d.get("class")},
                   score=d.get("score"), score_int8=d.get("score_int8"),
                   windows=d.get("windows"), rssi=d.get("rssi"), raw=payload)
        table = "alerts"
    elif topic.startswith("logguard/status/"):
        row = dict(device_id=d["device_id"], recv_us=recv_us, uptime_s=d.get("uptime_s"),
                   free_heap=d.get("free_heap"), pending=d.get("pending"), raw=payload)
        table = "status"
    else:
        return None
    cols = ", ".join(f'"{k}"' for k in row)
    db.execute(f"INSERT INTO {table}({cols}) VALUES({', '.join('?' * len(row))})",
               list(row.values()))
    db.commit()
    return row


def describe(topic, row):
    if topic.startswith("logguard/alerts/"):
        lat = f"{row['latency_ms']:.0f} ms" if row["latency_ms"] is not None else "n/a (clock not synced)"
        return (f"ALERT {row['device_id']} score={row['score']:.2f} windows={row['windows']} "
                f"rssi={row['rssi']} end-to-end={lat}")
    return f"status {row['device_id']} uptime={row['uptime_s']}s heap={row['free_heap']} pending={row['pending']}"


def main(argv=None):
    import paho.mqtt.client as mqtt

    p = argparse.ArgumentParser()
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    p.add_argument("--user", default="logguard")
    p.add_argument("--password", required=True)
    p.add_argument("--db", default="alerts.db")
    a = p.parse_args(argv)

    db = open_db(a.db)

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"connected to {a.host}:{a.port} ({reason_code})")
        client.subscribe([("logguard/alerts/#", 1), ("logguard/status/#", 1)])

    def on_message(client, userdata, msg):
        try:
            row = store(db, msg.topic, msg.payload.decode())
            if row:
                print(time.strftime("%H:%M:%S"), describe(msg.topic, row), flush=True)
        except (ValueError, KeyError) as e:
            print(f"bad message on {msg.topic}: {e}: {msg.payload!r}")

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="logguard-receiver")
    c.username_pw_set(a.user, a.password)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(a.host, a.port)
    c.loop_forever()


if __name__ == "__main__":
    main()
