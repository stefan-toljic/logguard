#!/bin/sh
# Send a fake alert to check the broker and receiver before the device exists.
#   ./test_publish.sh <password> [host]
set -eu
PASS="$1"; HOST="${2:-localhost}"
NOW_US=$(python3 -c 'import time; print(int(time.time()*1e6))')
mosquitto_pub -h "$HOST" -u logguard -P "$PASS" -q 1 -t logguard/alerts/lg-test \
  -m "{\"device_id\":\"lg-test\",\"ts_us\":$NOW_US,\"time_synced\":true,\"class\":\"chainsaw\",\"score\":0.93,\"score_int8\":110,\"windows\":3,\"rssi\":-55}"
echo "sent; the receiver should print an ALERT line"
