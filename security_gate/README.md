# Alpha 安檢門（Alpha Security Gate）

送模擬之前，先把「一定會失敗」的表達式擋下來，免得白燒模擬額度。
像機場安檢：有問題的表達式不准登機。

> 「Alpha 守門雙俠」之一：**安檢門管進場**（送模擬前），**囤貨婆管出貨**（繳交前，見 `../inventory_keeper/`）。

- 只用 Python 標準函式庫，`gate.py` 離線執行，不呼叫 simulation API。
- `catalog_export.py` 只做唯讀 GET，抓你帳號看得到的欄位與運算子清單。
- 跟我正式系統的檢查逐批比對（2026-11-25）：
  - 正式系統擋下的 **19 批**，分享版也全擋，擋的原因逐項一樣。
  - 正式系統放行的 **59 批**，分享版也全放行，沒有誤擋。

## 會擋什麼

| 種類 | 意思 | 我真的遇過的例子 |
|---|---|---|
| `missing_field` | 欄位在這個 region/universe/delay 不存在 | 自己猜的 `opt40_ivcall40`、`oth551_beta_vol` |
| `vector_without_vec_op` | VECTOR 欄位沒先用 `vec_*` 包起來 | `earnings_volatility_risk_premium` 直接拿去 `ts_backfill` |
| `unknown_operator` | 運算子不在你帳號的清單 | — |
| `wrong_arity`／`unbalanced_parens` | 參數個數不對、括號不成對 | `ts_mean(close)` 少了窗口 |
| `removed_field` | 欄位上次匯出還在、這次不見了（下架） | — |
| `unfilled_placeholder` | GA template 的 `<佔位符>` 沒給值 | — |

只提醒、不擋：gene 只是在換中性化方式、neutralization 屬 Power Pool 家族、你標記暫停的 region。

**PASS 不代表會賺錢**，只代表欄位、運算子、參數個數都對，送出去不會因為寫錯而報錯。

## 三步驟

```bash
# 1. 匯出你要研究的區域的欄位與運算子清單（第一次大區可能要幾十分鐘；之後每週重跑一次就好）
python catalog_export.py --session-pickle session.pkl --region USA --universe TOP3000 --delay 1 --out catalog/

# 2. 把要送的表達式一行一個寫進 txt（# 開頭是註解）
# 3. 檢查
python gate.py my_alphas.txt --region USA --universe TOP3000 --delay 1 --catalog catalog/
```

也可以直接檢查 GA template（`{"template": "...<field>...", "gene_pool": {"field": [...]}}`）或 seeds 檔
（`{"seeds": [{"expression": "..."}]}`），副檔名用 `.json`。template 會把每個 gene 的每個值都代進去檢查。

結束代碼：0＝可以送、1＝有會擋的問題、2＝無法判斷（例如沒匯出那個區）。可以直接接在你自己的排隊程式前面：
```bash
python gate.py batch.json --region USA --universe TOP3000 --catalog catalog/ && python my_submit_batch.py batch.json
```

## 範例（`example/`，真實資料）

`example/example_expressions.txt` 裡有 5 條：兩條是我 11/05、11/09 真的被擋的批次裡的表達式，一條是改好的版本，兩條是示範。
輸出（`example/example_output.txt`）：
```
共 5 個表達式：PASS 2、BLOCKED 3、無法判斷 0
第 2 行 BLOCKED：vrp = ts_backfill(earnings_volatility_risk_premium, 60); ...
  ✗ vector_without_vec_op earnings_volatility_risk_premium：VECTOR 欄位沒有先用 vec_* operator（例如 vec_avg）包起來，模擬會直接報錯
第 6 行 BLOCKED：skew = -1 * group_zscore(ts_mean(ts_backfill(subtract(opt40_ivput20, opt40_ivcall40), 60), ...
  ✗ missing_field opt40_ivcall40：USA/TOP3000/D1 沒有這個欄位
第 8 行 BLOCKED：rank(ts_mean(close))
  ✗ wrong_arity ts_mean：ts_mean 收 2 個參數，表達式給了 1 個
```

## 用 Claude Code（或其他 AI）當安檢員

把這段放進你的 `CLAUDE.md` 或 skill：

```
任何表達式或批次送模擬之前：
1. 一定先跑 python gate.py <檔案> --region ... --universe ... --delay ... --catalog catalog/
2. BLOCKED：逐條列出 ✗ 的種類、名稱、原因，改好再重跑到 PASS；不准建議「先送送看」。
3. 無法判斷（結束代碼 2）：明說沒檢查到，不當作 PASS。
4. 欄位名稱不確定時以 catalog 為準，不憑記憶說「應該有這個欄位」。
5. 看到 VECTOR 欄位，一律先用 vec_*（例如 vec_avg）包起來再用。
```

## 已知限制

- 它只擋「清單查得到的錯」。我的排隊紀錄裡，同期還有 18 批是送出後才在平台端失敗（例如只回一部分結果），這種它擋不到。
- 清單是匯出當下的快照；剛上架或剛下架的欄位，要重新匯出才知道。
- 只檢查 FastExpr；Python `@alpha` template 會回「無法判斷」。
- `catalog_export.py` 只在我自己的帳號實測過：GBR/TOP700/D1 匯出 18,294 個欄位，跟我正式系統每天同步的清單逐一比對完全相同。
  （平台的欄位計數最多只顯示到 10,000；第一版程式因此只抓到 10,000 個就停，已改成碰到上限就逐個 dataset 抓。）
