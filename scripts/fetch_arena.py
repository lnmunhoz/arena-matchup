#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyarrow>=15"]
# ///
"""Pull every Arena (arena.ai, formerly LMArena) leaderboard into SQLite + CSV.

Source: the official Hugging Face dataset `lmarena-ai/leaderboard-dataset`
(CC-BY-4.0), one parquet file per subset with `latest` and `full` splits.
arena.ai itself sits behind a Cloudflare challenge and has no public API.

Run:   uv run --with pyarrow python -I scripts/fetch_arena.py            # latest
       uv run --with pyarrow python -I scripts/fetch_arena.py --backfill # + all history

Idempotent: rows are keyed by (snapshot_date, subset, category, model, model_seq), where
snapshot_date is Arena's own publish date, so reruns add only new snapshots.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

import pyarrow.parquet as pq

DATASET = "lmarena-ai/leaderboard-dataset"
API = f"https://huggingface.co/api/datasets/{DATASET}"
RESOLVE = f"https://huggingface.co/datasets/{DATASET}/resolve/{{rev}}/{{path}}"
UA = "arena-leaderboard-fetch/1.0 (python-urllib)"

ROOT = Path(__file__).resolve().parent.parent
CHAT_ARENAS = {"text", "vision", "search", "document"}  # have a style-control twin

# source column -> our column
COLMAP = {
    "model_name": "model",
    "organization": "org",
    "license": "license",
    "rank": "rank",
    "category": "category",
    "leaderboard_publish_date": "snapshot_date",
    # Bradley-Terry arenas
    "rating": "score",
    "rating_lower": "ci_lower",
    "rating_upper": "ci_upper",
    "variance": "variance",
    "vote_count": "votes",
    # Agent Arena (IPS)
    "score": "score",
    "score_ci_lower": "ci_lower",
    "score_ci_upper": "ci_upper",
    "observation_count": "votes",
    "session_count": "sessions",
    "cost_per_task_p50": "cost_per_task_p50",
    "output_tokens_per_task_p50": "output_tokens_per_task_p50",
    # Agent capability / tool-efficiency / task-outcome index
    "index_score": "score",
    "index_score_ci_lower": "ci_lower",
    "index_score_ci_upper": "ci_upper",
    "raw_score": "raw_score",
    "raw_score_ci_lower": "raw_ci_lower",
    "raw_score_ci_upper": "raw_ci_upper",
}

COLUMNS = [
    "snapshot_date", "subset", "arena", "variant", "style_control", "site_default",
    "category", "rank", "model", "model_seq", "org", "license", "score_type", "score",
    "ci_lower", "ci_upper", "variance", "votes", "sessions", "raw_score",
    "raw_ci_lower", "raw_ci_upper", "cost_per_task_p50",
    "output_tokens_per_task_p50", "extra_json", "source_revision", "fetched_at",
]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS scores (
    snapshot_date TEXT NOT NULL,   -- Arena publish date (YYYY-MM-DD)
    subset        TEXT NOT NULL,   -- HF config name, e.g. text_style_control
    arena         TEXT NOT NULL,   -- text, vision, search, document, webdev, text_to_image, ...
    variant       TEXT NOT NULL,   -- raw | style_control | factuality | agent signal name
    style_control INTEGER NOT NULL,
    site_default  INTEGER NOT NULL,-- 1 = the variant arena.ai shows by default
    category      TEXT NOT NULL,   -- overall, coding, hard_prompts, math, webdev-react, ...
    rank          INTEGER,
    model         TEXT NOT NULL,
    model_seq     INTEGER NOT NULL DEFAULT 0, -- >0 only when Arena lists two entries with one name
    org           TEXT,
    license       TEXT,
    score_type    TEXT,            -- bt (Bradley-Terry rating) | ips | index
    score REAL, ci_lower REAL, ci_upper REAL, variance REAL,
    votes REAL, sessions REAL,
    raw_score REAL, raw_ci_lower REAL, raw_ci_upper REAL,
    cost_per_task_p50 REAL, output_tokens_per_task_p50 REAL,
    extra_json    TEXT,            -- any source column this script doesn't know yet
    source_revision TEXT,
    fetched_at    TEXT,
    PRIMARY KEY (snapshot_date, subset, category, model, model_seq)
);
CREATE INDEX IF NOT EXISTS scores_lookup ON scores(arena, variant, category, snapshot_date);
CREATE INDEX IF NOT EXISTS scores_model ON scores(model);
CREATE TABLE IF NOT EXISTS runs (
    fetched_at TEXT PRIMARY KEY, source_revision TEXT, split TEXT,
    rows_seen INTEGER, rows_new INTEGER
);
DROP VIEW IF EXISTS latest;
CREATE VIEW latest AS
SELECT s.* FROM scores s
JOIN (SELECT subset, category, MAX(snapshot_date) AS d FROM scores GROUP BY subset, category) m
  ON s.subset = m.subset AND s.category = m.category AND s.snapshot_date = m.d;
"""


def get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)


def classify(subset: str) -> tuple[str, str, int, int]:
    """subset -> (arena, variant, style_control, site_default)."""
    if subset == "agent" or subset.startswith("agent_"):
        signal = subset[len("agent_"):] or "aggregate"
        return "agent", signal, 0, int(subset == "agent")
    for suffix in ("_style_control", "_factuality"):
        if subset.endswith(suffix):
            arena = subset[: -len(suffix)]
            sc = int(suffix == "_style_control")
            return arena, suffix[1:], sc, sc  # site defaults to style control
    # raw variant: default on the site only when no style-control twin exists
    return subset, "raw", 0, int(subset not in CHAT_ARENAS)


def score_type(cols: set[str]) -> str:
    if "rating" in cols:
        return "bt"
    if "index_score" in cols:
        return "index"
    return "ips"


def normalize(subset: str, table, rev: str, fetched_at: str):
    arena, variant, sc, default = classify(subset)
    cols = set(table.column_names)
    stype = score_type(cols)
    src_rows = sorted(table.to_pylist(), key=lambda r: (r.get("rank") is None, r.get("rank") or 0))
    seq: dict[tuple, int] = {}
    for src in src_rows:
        row = dict.fromkeys(COLUMNS)
        extra = {}
        for k, v in src.items():
            dst = COLMAP.get(k)
            if dst is None:
                extra[k] = v
            elif row[dst] is None:
                row[dst] = v
        key = (row["snapshot_date"], row["category"], row["model"])
        row["model_seq"] = seq.get(key, 0)
        seq[key] = row["model_seq"] + 1
        if row["rank"] is not None:
            row["rank"] = int(row["rank"])
        row.update(
            subset=subset, arena=arena, variant=variant, style_control=sc,
            site_default=default, score_type=stype, source_revision=rev,
            fetched_at=fetched_at,
            extra_json=json.dumps(extra, default=str) if extra else None,
        )
        yield row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backfill", action="store_true", help="load the `full` split (all history, ~70 MB)")
    ap.add_argument("--only", nargs="*", help="limit to these subsets, e.g. text_style_control webdev")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "arena.sqlite")
    ap.add_argument("--csv", type=Path, default=ROOT / "data" / "arena_latest.csv")
    ap.add_argument("--raw-dir", type=Path, default=ROOT / "raw" / "hf")
    args = ap.parse_args()

    split = "full" if args.backfill else "latest"
    fetched_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    info = get_json(API)
    rev = info["sha"]
    files = sorted(
        s["rfilename"] for s in info["siblings"]
        if s["rfilename"].endswith(".parquet") and Path(s["rfilename"]).name.startswith(f"{split}-")
    )
    subsets: dict[str, list[str]] = {}
    for f in files:
        subsets.setdefault(f.split("/")[0], []).append(f)
    if args.only:
        missing = set(args.only) - subsets.keys()
        if missing:
            print(f"unknown subsets: {sorted(missing)}; have {sorted(subsets)}", file=sys.stderr)
            return 2
        subsets = {k: v for k, v in subsets.items() if k in args.only}
    if not subsets:
        print("no parquet files found; dataset layout changed?", file=sys.stderr)
        return 1

    args.db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(args.db)
    con.executescript(SCHEMA)
    before = con.execute("SELECT COUNT(*) FROM scores").fetchone()[0]

    placeholders = ",".join("?" * len(COLUMNS))
    updates = ",".join(f"{c}=excluded.{c}" for c in COLUMNS if c not in
                       ("snapshot_date", "subset", "category", "model", "model_seq", "fetched_at"))
    sql = (f"INSERT INTO scores ({','.join(COLUMNS)}) VALUES ({placeholders}) "
           f"ON CONFLICT(snapshot_date, subset, category, model, model_seq) DO UPDATE SET {updates}")

    seen = 0
    cache = args.raw_dir / rev[:12]
    for subset, paths in sorted(subsets.items()):
        n = 0
        for p in paths:
            dest = cache / p
            download(RESOLVE.format(rev=rev, path=p), dest)
            rows = [tuple(r[c] for c in COLUMNS) for r in normalize(subset, pq.read_table(dest), rev, fetched_at)]
            con.executemany(sql, rows)
            n += len(rows)
        seen += n
        print(f"  {subset:32s} {n:>8,} rows")
    after = con.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    con.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)", (fetched_at, rev, split, seen, after - before))
    con.commit()

    cur = con.execute("SELECT * FROM latest ORDER BY arena, variant, category, rank, model")
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with open(args.csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([d[0] for d in cur.description])
        latest_n = 0
        for r in cur:
            w.writerow(r)
            latest_n += 1
    con.close()

    print(f"revision {rev[:12]}  split={split}  seen={seen:,}  new={after - before:,}  total={after:,}")
    print(f"wrote {args.db}  and  {args.csv} ({latest_n:,} latest rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
