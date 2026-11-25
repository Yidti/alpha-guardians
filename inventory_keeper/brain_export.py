#!/usr/bin/env python3
"""從 Brain 平台匯出囤貨婆要的資料（只用唯讀 GET，不送模擬、不繳交）。

你需要一個「已登入」的 requests.Session（open machine 通常已經有，例如 session.pkl）。
本程式不處理帳密，也不會把 session 寫到別處。

用法（命令列）：
    python brain_export.py --session-pickle session.pkl --ids ids.txt --out my_data/ --recent-days 14
        ids.txt：你的候選 alpha id，一行一個（已經模擬過、你覺得可以繳的）

用法（在自己的程式裡）：
    from brain_export import export
    export(my_session, ["abc123", "def456"], "my_data", recent_days=14)

會寫出：pyramid.json、candidates.json、pnl/<id>.csv、submitted_after.json
"""
from __future__ import annotations

import argparse
import json
import pickle
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

API = "https://api.worldquantbrain.com"


def _get(s, url, params=None, tries=5):
    for _ in range(tries):
        r = s.get(url, params=params, timeout=60)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 10)))
            continue
        if r.status_code == 401:
            raise SystemExit("Brain 登入過期（401），請重新登入後再跑")
        if r.status_code == 200 and not r.text.strip():
            time.sleep(10)          # 平台還在算 /check，等一下再問
            continue
        return r
    return r


def _cat(c):
    return c.get("id") if isinstance(c, dict) else c


def quarter_window(today: date):
    qs = date(today.year, (today.month - 1) // 3 * 3 + 1, 1)
    qe = date(qs.year + (qs.month + 2) // 12, (qs.month + 2) % 12 + 1, 1)
    return qs.isoformat(), qe.isoformat()


def export_pyramid(s, out: Path):
    qs, qe = quarter_window(date.today())
    mult = _get(s, f"{API}/users/self/activities/pyramid-multipliers").json().get("pyramids", [])
    cnt = _get(s, f"{API}/users/self/activities/pyramid-alphas", {"startDate": qs, "endDate": qe}).json().get("pyramids", [])
    cells = {}
    for e in mult:
        k = f"{e['region']}/D{int(e['delay'])}/{_cat(e['category'])}".upper()
        cells.setdefault(k, {"cell": k, "submitted": 0})["multiplier"] = e.get("multiplier")
    for e in cnt:
        k = f"{e['region']}/D{int(e['delay'])}/{_cat(e['category'])}".upper()
        cells.setdefault(k, {"cell": k, "multiplier": None})["submitted"] = int(e.get("alphaCount") or 0)
    (out / "pyramid.json").write_text(json.dumps(list(cells.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    return len(cells)


def write_pnl(s, aid: str, out: Path) -> bool:
    r = _get(s, f"{API}/alphas/{aid}/recordsets/pnl")
    recs = (r.json() or {}).get("records", []) if r.status_code == 200 and r.text.strip() else []
    if not recs:
        return False
    (out / "pnl").mkdir(exist_ok=True)
    with (out / "pnl" / f"{aid}.csv").open("w", encoding="utf-8") as f:
        f.write("date,pnl\n")
        for x in recs:
            if len(x) > 1 and x[1] is not None:
                f.write(f"{x[0]},{x[1]}\n")
    return True


def export_candidate(s, aid: str, out: Path) -> dict:
    a = _get(s, f"{API}/alphas/{aid}").json()
    st = a.get("is") or {}
    settings = a.get("settings") or {}
    r = _get(s, f"{API}/alphas/{aid}/check")
    try:
        chk = (r.json().get("is") or {}).get("checks", [])
    except ValueError:          # 平台還在算 /check（回空白）：標 PENDING，囤貨婆會先不收它
        chk = []
    by = {c.get("name"): c for c in chk}
    if not chk:
        by = {"PROD_CORRELATION": {"result": "PENDING"}, "SELF_CORRELATION": {"result": "PENDING"}}
    pyr = by.get("MATCHES_PYRAMID") or {}
    return {
        "alpha_id": aid,
        "region": settings.get("region"),
        "cells": [p.get("name") for p in pyr.get("pyramids", []) if isinstance(p, dict) and p.get("name")],
        "sharpe": st.get("sharpe"), "fitness": st.get("fitness"), "turnover": st.get("turnover"),
        "margin": st.get("margin"),
        "prod_corr": (by.get("PROD_CORRELATION") or {}).get("value"),
        "self_corr": (by.get("SELF_CORRELATION") or {}).get("value"),
        "prod_check": (by.get("PROD_CORRELATION") or {}).get("result"),
        "self_check": (by.get("SELF_CORRELATION") or {}).get("result"),
        "has_pnl": write_pnl(s, aid, out),
    }


def recent_submitted(s, days: int) -> list:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    r = _get(s, f"{API}/users/self/alphas", {"limit": 100, "offset": 0, "order": "-dateSubmitted",
                                              "status": "ACTIVE", "hidden": "false"})
    rows = r.json().get("results", []) if r.status_code == 200 else []
    out = []
    for x in rows:
        ds = x.get("dateSubmitted")
        if ds and datetime.fromisoformat(ds.replace("Z", "+00:00")) >= since:
            out.append(x["id"])
    return out


def export(session, ids, out_dir, recent_days: int = 14):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = export_pyramid(session, out)
    cands = []
    for i, aid in enumerate(ids, 1):
        cands.append(export_candidate(session, aid, out))
        print(f"  候選 {i}/{len(ids)} {aid}：{'、'.join(cands[-1]['cells']) or '沒落在任何格子'}")
    (out / "candidates.json").write_text(json.dumps(cands, ensure_ascii=False, indent=1), encoding="utf-8")
    subs = [x for x in recent_submitted(session, recent_days) if x not in ids] if recent_days else []
    subs = [x for x in subs if write_pnl(session, x, out)]
    (out / "submitted_after.json").write_text(json.dumps(subs), encoding="utf-8")
    print(f"完成：{n} 格 pyramid、{len(cands)} 支候選、最近 {recent_days} 天已繳 {len(subs)} 支 → {out}")


def main():
    ap = argparse.ArgumentParser(description="從 Brain 匯出囤貨婆的資料（唯讀）")
    ap.add_argument("--session-pickle", required=True, help="已登入的 requests.Session（pickle 檔）")
    ap.add_argument("--ids", required=True, help="候選 alpha id 清單檔，一行一個")
    ap.add_argument("--out", default="data")
    ap.add_argument("--recent-days", type=int, default=14,
                    help="最近幾天繳的 alpha 也抓 PnL，檢查候選會不會跟它們打架（0＝不抓）")
    a = ap.parse_args()
    with open(a.session_pickle, "rb") as f:
        session = pickle.load(f)
    ids = [x.strip() for x in Path(a.ids).read_text(encoding="utf-8").splitlines() if x.strip()]
    export(session, ids, a.out, a.recent_days)


if __name__ == "__main__":
    main()
