"""
Shadow Observer — Adaptive V2, Step 3

مراقب ظل: لكل صفقة في الدفتر الحقيقي يسجّل لقطة خصائص عند لحظة فتحها
(تُحسب رجعياً بانضباط as_of — الشموع المغلقة فقط كما كانت عند الفتح)،
ويربط النتيجة الفعلية عند إغلاق الصفقة. لا يكتب إلا داخل مجلد shadow/
هنا — الدفتر الحقيقي وقاعدة الشموع قراءة فقط.

التشغيل: python3 shadow_observer.py [--quiet]
المخرجات: shadow/snapshots.jsonl + shadow/outcomes.jsonl + shadow/state.json
"""

import json
import sys
from pathlib import Path

import features

BASE = Path(__file__).resolve().parent
LEDGER = BASE.parent / "gold_ledger.json"
SHADOW = BASE / "shadow"
SNAP = SHADOW / "snapshots.jsonl"
OUTC = SHADOW / "outcomes.jsonl"
STATE = SHADOW / "state.json"


def _load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"snapshotted": [], "outcomed": []}


def _trades():
    data = json.loads(LEDGER.read_text())
    return data if isinstance(data, list) else data.get("trades", [])


def load_snapshots():
    out = {}
    if SNAP.exists():
        for line in SNAP.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["trade_id"]] = r
    return out


def load_outcomes():
    out = {}
    if OUTC.exists():
        for line in OUTC.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["trade_id"]] = r
    return out


def run(quiet=False):
    SHADOW.mkdir(exist_ok=True)
    state = _load_state()
    snapped = set(state["snapshotted"])
    outcomed = set(state["outcomed"])
    trades = _trades()
    new_snaps, new_outs, errors = 0, 0, []

    with SNAP.open("a") as fsnap, OUTC.open("a") as fout:
        for tr in trades:
            tid = tr.get("id")
            if tid is None:
                continue
            if tid not in snapped:
                try:
                    rec = {
                        "trade_id": tid,
                        "strategy": tr.get("strategy"),
                        "dir": tr.get("dir"),
                        "ts_open": tr.get("ts_open"),
                        "entry": tr.get("entry"),
                        "features": features.snapshot(tr),
                    }
                    fsnap.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    snapped.add(tid)
                    new_snaps += 1
                except Exception as e:  # صفقة واحدة معطوبة لا توقف المراقب
                    errors.append(f"trade {tid}: {e}")
            if tid not in outcomed and tr.get("status") not in (None, "open"):
                fout.write(json.dumps({
                    "trade_id": tid,
                    "status": tr.get("status"),
                    "r_multiple": tr.get("r_multiple"),
                    "ts_close": tr.get("ts_close"),
                    "mfe_r": tr.get("mfe_r"),
                    "mae_r": tr.get("mae_r"),
                }, ensure_ascii=False) + "\n")
                outcomed.add(tid)
                new_outs += 1

    state["snapshotted"] = sorted(snapped)
    state["outcomed"] = sorted(outcomed)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    if not quiet:
        print(f"observer: trades={len(trades)} new_snapshots={new_snaps} "
              f"new_outcomes={new_outs} total_snapshots={len(snapped)} "
              f"total_outcomes={len(outcomed)}")
        for e in errors:
            print("  ERROR:", e)
    return {"new_snapshots": new_snaps, "new_outcomes": new_outs,
            "errors": errors}


if __name__ == "__main__":
    run(quiet="--quiet" in sys.argv)
