#!/usr/bin/env bash
# etcd WAL fsync latency and leader stability, read from each server's own
# metrics endpoint (k3s serves it on 127.0.0.1:2381).
#
# fsync is how long the disk takes to make a raft log entry durable. etcd
# starts warning around 100ms; under 25ms is comfortable. Counters are
# cumulative since etcd started, so a freshly bootstrapped node looks worse
# than it is - the bootstrap write burst is still in the sample.
set -euo pipefail

cd "$(dirname "$0")/../infra/ansible"

ansible all -i inventory/hosts.yml -b -m shell -a \
  "curl -s http://127.0.0.1:2381/metrics | grep -E '^etcd_disk_wal_fsync_duration_seconds|^etcd_server_has_leader|^etcd_server_leader_changes_seen_total'" \
  2>/dev/null | awk '
  /^[a-zA-Z0-9_-]+ \| / { host = $1; hosts[host] = 1; next }
  /^etcd_disk_wal_fsync_duration_seconds_bucket/ { split($0, q, "\""); b[host, q[2]] = $NF }
  /^etcd_disk_wal_fsync_duration_seconds_sum/    { sum[host]   = $NF }
  /^etcd_disk_wal_fsync_duration_seconds_count/  { count[host] = $NF }
  /^etcd_server_has_leader/                      { leader[host] = $NF }
  /^etcd_server_leader_changes_seen_total/       { changes[host] = $NF }
  function pct(host, le,   n) {
    n = b[host, le]
    return (count[host] > 0) ? sprintf("%.1f%%", 100 * n / count[host]) : "-"
  }
  END {
    printf "%-10s %8s %9s %8s %8s %8s %7s %8s\n", \
      "NODE", "FSYNCS", "MEAN", "<8ms", "<16ms", "<64ms", "LEADER", "ELECTIONS"
    for (h in hosts) {
      printf "%-10s %8d %7.1fms %8s %8s %8s %7s %8d\n", h, count[h], \
        (count[h] > 0 ? 1000 * sum[h] / count[h] : 0), \
        pct(h, "0.008"), pct(h, "0.016"), pct(h, "0.064"), \
        (leader[h] == 1 ? "yes" : "NO"), changes[h]
    }
  }' | { read -r hdr; echo "$hdr"; sort; }
