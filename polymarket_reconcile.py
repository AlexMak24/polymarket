#!/usr/bin/env python3
"""One-shot: reconcile unresolved Polymarket resolutions via Gamma."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import polymarket_collector as C
import polymarket_db as DB


def count_unresolved(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM markets WHERE end_date < ? "
        "AND (resolution_status IS NULL OR resolution_status = '')",
        (DB.now_iso(),),
    ).fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconcile unresolved Polymarket resolutions")
    ap.add_argument("--db", default=None, help="path to SQLite DB")
    ap.add_argument("--limit", type=int, default=200, help="batch size")
    ap.add_argument("--sleep", type=float, default=0.05, help="pause between batches")
    ap.add_argument("--max-batches", type=int, default=0, help="0 = until stall/empty")
    ap.add_argument("--offset-step", action="store_true",
                    help="advance OFFSET when a batch marks 0 (skip stuck rows)")
    args = ap.parse_args()

    conn = DB.connect(args.db)
    DB.init_db(conn)

    before = count_unresolved(conn)
    print(f"unresolved before: {before}", flush=True)

    total = 0
    batch_i = 0
    offset = 0
    stall_skips = 0
    while True:
        batch_i += 1
        if args.max_batches and batch_i > args.max_batches:
            break
        pending = DB.unresolved_markets(conn, args.limit, offset=offset)
        if not pending:
            print("no pending unresolved", flush=True)
            break
        n = C.reconcile_resolutions(conn, limit=args.limit, offset=offset)
        total += n
        left = count_unresolved(conn)
        print(
            f"batch {batch_i}: marked={n} total_marked={total} "
            f"unresolved_left={left} offset={offset}",
            flush=True,
        )
        if n == 0:
            if args.offset_step:
                offset += args.limit
                stall_skips += 1
                if stall_skips > 20 or offset >= before + args.limit:
                    print("stall: too many empty offset steps — stopping", flush=True)
                    break
                continue
            print("stall: 0 marked this batch — stopping", flush=True)
            break
        stall_skips = 0
        time.sleep(args.sleep)

    after = count_unresolved(conn)
    print(f"unresolved after: {after}", flush=True)
    print(f"marked total: {total}", flush=True)
    print(f"stats: {DB.stats(conn)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
