#!/usr/bin/env python3
"""匯出 Alpha 安檢門要的「欄位清單」和「運算子清單」（只用唯讀 GET）。

你需要一個已登入的 requests.Session（open machine 通常已經有，例如 session.pkl）。
每個 region/universe/delay 跑一次；之後每天或每週重跑，就會記錄哪些欄位下架了。

    python catalog_export.py --session-pickle session.pkl --region USA --universe TOP3000 --delay 1 --out catalog/

寫出：
    catalog/operators.json
    catalog/datafields_USA_TOP3000_1d_latest.json   （每個欄位的 id 與 type，VECTOR 判斷靠它）
    catalog/.catalog-changes.jsonl                  （跟上次比，新增／下架的欄位）

平台 /data-fields 一次最多翻到 10,000 筆；超過時改成逐個 dataset 抓。
每次請求間隔約 3 秒（平台對 /data-fields 有每分鐘次數限制），大區第一次匯出可能要幾十分鐘。
"""
from __future__ import annotations

import argparse
import json
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.worldquantbrain.com"
PAGE = 50
CAP = 10000
SPACING = 3.0


def get(s, path, params=None, tries=6):
    for _ in range(tries):
        time.sleep(SPACING)
        r = s.get(f"{API}{path}", params=params, timeout=60)
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 30)))
            continue
        if r.status_code == 401:
            raise SystemExit("Brain 登入過期（401），請重新登入後再跑")
        if r.status_code == 200:
            return r.json()
    raise SystemExit(f"{path} 一直失敗（HTTP {r.status_code}）")


def page_all(s, path, base):
    first = get(s, path, dict(base, limit=PAGE, offset=0))
    rows, count = list(first.get("results", [])), int(first.get("count") or 0)
    for off in range(PAGE, min(count, CAP), PAGE):
        rows += get(s, path, dict(base, limit=PAGE, offset=off)).get("results", [])
    return rows, count


def export(session, region, universe, delay, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ops = get(session, "/operators")
    ops = ops if isinstance(ops, list) else ops.get("results", [])
    (out / "operators.json").write_text(json.dumps(ops, ensure_ascii=False), encoding="utf-8")
    print(f"operators：{len(ops)} 個")

    base = {"instrumentType": "EQUITY", "region": region, "delay": delay, "universe": universe}
    rows, count = page_all(session, "/data-fields", base)
    if count >= CAP:   # 平台計數最多顯示到 10,000：到頂就代表可能更多，改逐個 dataset 抓（實測 GBR 實際 18,295 個）
        sets, _ = page_all(session, "/data-sets", base)
        rows = []
        for i, ds in enumerate(sets, 1):
            got, _ = page_all(session, "/data-fields", dict(base, **{"dataset.id": ds["id"]}))
            rows += got
            print(f"  dataset {i}/{len(sets)} {ds['id']}：{len(got)} 個欄位")
    fields = {r["id"]: {"id": r["id"], "type": r.get("type", ""), "dataset": (r.get("dataset") or {}).get("id", "")}
              for r in rows if isinstance(r, dict) and r.get("id")}

    name = f"datafields_{region}_{universe}_{delay}d_latest.json"
    old_path = out / name
    if old_path.exists():
        old = {r["id"] for r in json.loads(old_path.read_text(encoding="utf-8")) if isinstance(r, dict)}
        added, removed = sorted(set(fields) - old), sorted(old - set(fields))
        if added or removed:
            with (out / ".catalog-changes.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"scope": name[:-5], "at": datetime.now(timezone.utc).isoformat(),
                                    "added": added, "removed": removed}, ensure_ascii=False) + "\n")
            print(f"跟上次比：新增 {len(added)}、下架 {len(removed)}")
    old_path.write_text(json.dumps(list(fields.values()), ensure_ascii=False), encoding="utf-8")
    vec = sum(1 for v in fields.values() if str(v["type"]).upper() == "VECTOR")
    print(f"{region}/{universe}/D{delay}：{len(fields)} 個欄位（其中 VECTOR {vec} 個）→ {old_path}")


def main():
    ap = argparse.ArgumentParser(description="匯出 Alpha 安檢門的欄位／運算子清單（唯讀）")
    ap.add_argument("--session-pickle", required=True, help="已登入的 requests.Session（pickle 檔）")
    ap.add_argument("--region", required=True)
    ap.add_argument("--universe", required=True)
    ap.add_argument("--delay", type=int, default=1)
    ap.add_argument("--out", default="catalog")
    a = ap.parse_args()
    with open(a.session_pickle, "rb") as f:
        session = pickle.load(f)
    export(session, a.region.upper(), a.universe.upper(), a.delay, a.out)


if __name__ == "__main__":
    main()
