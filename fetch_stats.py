#!/usr/bin/env python3
"""
LeetCode Stats Fetcher

Fetches stats for two rosters and writes data.json:
  usernames.txt       — your real crew
  usernames.demo.txt  — reference/demo accounts (marked demo:true in output)

Also tracks weekly and monthly rank snapshots so the UI can show
↑/↓ movement in the leaderboard over time.

Usage:
    pip install -r requirements.txt
    python fetch_stats.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    sys.exit("Run: pip install requests")

# ── Configuration ──────────────────────────────────────────────────────────────

LEETCODE_GRAPHQL  = "https://leetcode.com/graphql"
USERNAMES_FILE    = "usernames.txt"
DEMO_FILE         = "usernames.demo.txt"
OUTPUT_FILE       = "data.json"
REQUEST_DELAY     = 1.5   # seconds between requests — be polite
REQUEST_TIMEOUT   = 15    # seconds per request

HEADERS = {
    "Content-Type": "application/json",
    "Referer":      "https://leetcode.com",
    "User-Agent":   "Mozilla/5.0 (LCGrind-LeaderboardBot/1.0)",
}

# ── Roster loading ─────────────────────────────────────────────────────────────

def load_usernames(path: str, optional: bool = False) -> list[str]:
    """Read one username per line; skip blanks and # comments."""
    if not os.path.exists(path):
        if optional:
            return []
        sys.exit(
            f"Error: '{path}' not found.\n"
            "Create it with one LeetCode username per line."
        )
    with open(path, encoding="utf-8") as fh:
        names = [
            line.strip()
            for line in fh
            if line.strip() and not line.strip().startswith("#")
        ]
    if not names and not optional:
        sys.exit(f"Error: '{path}' contains no usernames.")
    return names

# ── GraphQL query ──────────────────────────────────────────────────────────────

QUERY = """
query getUserProfile($username: String!, $year: Int) {
  matchedUser(username: $username) {
    submitStats: submitStatsGlobal {
      acSubmissionNum {
        difficulty
        count
      }
    }
    userCalendar(year: $year) {
      streak
      submissionCalendar
    }
  }
}
"""

# ── Calendar helpers ───────────────────────────────────────────────────────────

def day_ts(offset: int = 0) -> int:
    """Unix timestamp for the start of UTC day, `offset` days ago."""
    now = datetime.now(timezone.utc)
    d   = now - timedelta(days=offset)
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def parse_calendar(raw: str | None) -> dict[int, int]:
    if not raw:
        return {}
    try:
        return {int(k): int(v) for k, v in json.loads(raw).items()}
    except Exception:
        return {}


def window_sum(cal: dict[int, int], start_days_ago: int, end_days_ago: int = 0) -> int:
    """Sum calendar values in the closed window [start_days_ago, end_days_ago]."""
    lo = day_ts(start_days_ago)
    hi = day_ts(end_days_ago) + 86_399  # inclusive end of day
    return sum(v for ts, v in cal.items() if lo <= ts <= hi)

# ── Fetch logic ────────────────────────────────────────────────────────────────

def fetch_user(username: str) -> dict | None:
    year = datetime.now(timezone.utc).year
    try:
        resp = requests.post(
            LEETCODE_GRAPHQL,
            json={
                "query":         QUERY,
                "variables":     {"username": username, "year": year},
                "operationName": "getUserProfile",
            },
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data    = resp.json().get("data", {})
        matched = data.get("matchedUser")

        if not matched:
            print(f"  ✗  '{username}' not found on LeetCode")
            return None

        counts = {
            item["difficulty"]: item["count"]
            for item in matched["submitStats"]["acSubmissionNum"]
        }

        cal_obj = matched.get("userCalendar") or {}
        cal     = parse_calendar(cal_obj.get("submissionCalendar"))

        daily  = window_sum(cal, 0)
        weekly = window_sum(cal, 6)
        prev_w = window_sum(cal, 13, 7)

        return {
            "username":     username,
            "totalSolved":  counts.get("All",    0),
            "easySolved":   counts.get("Easy",   0),
            "mediumSolved": counts.get("Medium", 0),
            "hardSolved":   counts.get("Hard",   0),
            "streak":       (cal_obj.get("streak") or 0),
            "dailySolved":  daily,
            "weeklySolved": weekly,
            "weeklyDelta":  weekly - prev_w,
        }

    except requests.exceptions.Timeout:
        print(f"  ✗  Timeout for '{username}'")
    except requests.exceptions.HTTPError as e:
        print(f"  ✗  HTTP {e.response.status_code} for '{username}'")
    except Exception as e:
        print(f"  ✗  Error for '{username}': {e}")
    return None

# ── Rank snapshot helpers ──────────────────────────────────────────────────────

def load_prev_full(path: str) -> dict:
    """Return the full existing data.json, or a minimal empty structure."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def snapshot_stale(snap: dict | None, days: int) -> bool:
    """True if snapshot is absent or older than `days` days."""
    if not snap:
        return True
    try:
        ts = datetime.fromisoformat(snap["date"].replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - ts >= timedelta(days=days)
    except Exception:
        return True


def ranks_from_results(results: list[dict]) -> dict[str, int]:
    """Return {username: rank (1-based)} from a sorted result list."""
    return {u["username"]: i + 1 for i, u in enumerate(results)}


def apply_rank_deltas(results: list[dict], snapshots: dict) -> None:
    """Attach rankDeltaWeek and rankDeltaMonth to each result in-place."""
    week_ranks  = (snapshots.get("week")  or {}).get("ranks", {})
    month_ranks = (snapshots.get("month") or {}).get("ranks", {})
    for i, u in enumerate(results):
        cur = i + 1
        prev_w = week_ranks.get(u["username"])
        prev_m = month_ranks.get(u["username"])
        u["rankDeltaWeek"]  = (prev_w - cur) if prev_w is not None else None
        u["rankDeltaMonth"] = (prev_m - cur) if prev_m is not None else None

# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    real_names = load_usernames(USERNAMES_FILE)
    demo_names = load_usernames(DEMO_FILE, optional=True)

    all_entries: list[tuple[str, bool]] = (
        [(n, False) for n in real_names] +
        [(n, True)  for n in demo_names]
    )

    total = len(all_entries)
    real_count = len(real_names)
    demo_count = len(demo_names)
    print(f"⚡  LC Grind — fetching {total} user(s)  "
          f"({real_count} crew · {demo_count} demo)\n")

    prev_full = load_prev_full(OUTPUT_FILE)
    prev_map  = {u["username"]: u for u in (prev_full.get("users") or [])}
    snapshots = dict(prev_full.get("snapshots") or {})

    results: list[dict] = []
    failed:  list[str]  = []

    for i, (name, is_demo) in enumerate(all_entries):
        tag = " [demo]" if is_demo else ""
        print(f"  [{i+1:>2}/{total}]  {name}{tag} ...", end="  ", flush=True)
        stats = fetch_user(name)

        if stats:
            old = prev_map.get(name, {})
            stats["totalDelta"] = stats["totalSolved"] - (old.get("totalSolved") or stats["totalSolved"])
            if is_demo:
                stats["demo"] = True
            results.append(stats)
            print(
                f"✓  total={stats['totalSolved']:>4}  "
                f"week={stats['weeklySolved']:>3}  "
                f"day={stats['dailySolved']:>2}  "
                f"streak={stats['streak']}d  "
                f"Δ={stats['totalDelta']:+d}"
            )
        else:
            failed.append(name)

        if i < total - 1:
            time.sleep(REQUEST_DELAY)

    results.sort(key=lambda u: u["totalSolved"], reverse=True)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Update stale snapshots BEFORE attaching deltas (old snapshot → delta)
    if snapshot_stale(snapshots.get("week"), 7):
        snapshots["week"] = {"date": now_iso, "ranks": ranks_from_results(results)}
        print("\n📸  Weekly rank snapshot updated.")
    if snapshot_stale(snapshots.get("month"), 30):
        snapshots["month"] = {"date": now_iso, "ranks": ranks_from_results(results)}
        print("📸  Monthly rank snapshot updated.")

    apply_rank_deltas(results, snapshots)

    output = {
        "lastUpdated": now_iso,
        "snapshots":   snapshots,
        "users":       results,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\n✅  {len(results)} users written → {OUTPUT_FILE}")
    if failed:
        print(f"⚠️   Skipped {len(failed)}: {', '.join(failed)}")


if __name__ == "__main__":
    main()
