# Alpha 守門雙俠（Alpha Guardians）

WorldQuant BRAIN 顧問用的兩個小幫手，2026 Q4 Local Agent Challenge 投稿作品。

| | 守在哪 | 解決什麼問題 | 資料夾 |
|---|---|---|---|
| 🚪 **Alpha 安檢門** | 送模擬**之前** | 欄位名稱打錯、VECTOR 欄位忘了包 `vec_*`、參數個數不對……送出去整批報錯，模擬額度白燒 | [`security_gate/`](security_gate/) |
| 🧺 **Alpha 囤貨婆** | 繳交**之前** | 找到就繳：繳進已經滿 3 支的 pyramid 格子、繳了一支讓另一支永遠 SELF FAIL、庫存永遠是 0 | [`inventory_keeper/`](inventory_keeper/) |

一句話：**安檢門管進場，囤貨婆管出貨。**

---

## 目錄

1. [它們不會做的事（安全）](#1-它們不會做的事安全)
2. [你需要準備什麼](#2-你需要準備什麼)
3. [下載](#3-下載)
4. [準備已登入的 session](#4-準備已登入的-session)
5. [Alpha 安檢門：一步一步用](#5-alpha-安檢門一步一步用)
6. [Alpha 囤貨婆：一步一步用](#6-alpha-囤貨婆一步一步用)
7. [搭配 Claude Code（或其他 AI）](#7-搭配-claude-code或其他-ai)
8. [常見問題](#8-常見問題)
9. [怎麼確認它們是對的](#9-怎麼確認它們是對的)
10. [版本、授權、回報問題](#10-版本授權回報問題)

---

## 1. 它們不會做的事（安全）

- **不呼叫 simulation API**：不會幫你送任何模擬。
- **不會幫你繳交**：囤貨婆只給建議，繳交永遠由你自己按。
- **不碰帳密**：程式不讀、不存你的帳號密碼。匯出資料時用的是你自己已經登入好的 session。
- **匯出只做唯讀 GET**：`catalog_export.py`、`brain_export.py` 只「讀」平台資料（欄位清單、/check 結果、PnL、pyramid 狀態）。
- **檢查與判斷完全離線**：`gate.py`、`keeper.py` 不連網路。

---

## 2. 你需要準備什麼

| 項目 | 說明 |
|---|---|
| Python 3.9 以上 | 只用標準函式庫，**不用 pip 安裝任何套件**。Windows 可用 `py` 代替 `python`。 |
| BRAIN 帳號 | 只有匯出資料那一步要用。 |
| 已登入的 `requests.Session` | 只有匯出那一步要用，見第 4 節。（`requests` 是你登入用的程式本來就有的，本專案的檢查程式不需要它。） |

---

## 3. 下載

```bash
git clone https://github.com/Yidti/alpha-guardians.git
cd alpha-guardians
```

不會用 git 的話：在 GitHub 頁面按綠色的 **Code → Download ZIP**，解壓縮就好。

先試跑一次確認環境沒問題（不用登入）：

```bash
cd inventory_keeper
python keeper.py --config config.example.json --data example_data --today 2026-11-25
```

看到「庫存 30 支（能補格子 17、格子已滿 13）……」開頭的輸出就代表可以用了。

---

## 4. 準備已登入的 session

兩支匯出程式都吃一個 **pickle 起來的、已登入的 `requests.Session`**（常見檔名 `session.pkl`）。

- **你用的 open machine／研究工具已經有登入好的 session**：多半已經存在某個 `.pkl` 檔，直接指給 `--session-pickle` 就好。
- **你手上有一個登入好的 session 物件**（例如變數叫 `sess`），存成檔案：

  ```python
  import pickle
  with open("session.pkl", "wb") as f:
      pickle.dump(sess, f)
  ```

- 登入過期時，匯出程式會停下來告訴你「登入過期（401）」，重新登入、重存 `session.pkl` 再跑就好。

⚠️ `session.pkl` 等同你的登入憑證，**不要上傳、不要分享**。本專案的 `.gitignore` 已經排除 `*.pkl`。

---

## 5. Alpha 安檢門：一步一步用

### 5-1. 匯出你要研究的區的「欄位清單」和「運算子清單」

```bash
cd security_gate
python catalog_export.py --session-pickle ../session.pkl --region USA --universe TOP3000 --delay 1 --out catalog/
```

- 每個 region／universe／delay 各跑一次。例如也做 EUR：`--region EUR --universe TOP2500`。
- **第一次會跑比較久**：平台有限速，程式每次請求間隔約 3 秒；欄位超過 10,000 個的大區要逐個 dataset 抓，可能幾十分鐘。之後每週重跑一次就好。
- 重跑時會記下「上次有、這次不見」的欄位（下架），之後用到這些欄位會被標成 `removed_field`。

跑完 `catalog/` 會有：
```
catalog/operators.json
catalog/datafields_USA_TOP3000_1d_latest.json
catalog/.catalog-changes.jsonl      （第二次之後才有）
```

### 5-2. 準備要檢查的東西

三種格式都可以：

**(a) 一行一個表達式的 `.txt`**（`#` 開頭是註解）
```
# 我今天想試的
rank(-ts_delta(close, 5))
vrp = ts_backfill(vec_avg(earnings_volatility_risk_premium), 60); rank(vrp)
```

**(b) GA template（`.json`）**：每個 gene 的每個值都會代進去檢查一次。
```json
{"template": "rank(ts_mean(<field>, <window>))",
 "gene_pool": {"field": ["close", "volume"], "window": ["5", "20"]}}
```

**(c) seeds 檔（`.json`）**
```json
{"seeds": [{"expression": "rank(-ts_delta(close, 5))"}]}
```

### 5-3. 檢查

```bash
python gate.py my_alphas.txt --region USA --universe TOP3000 --delay 1 --catalog catalog/
```

可選參數：`--neutralization SUBINDUSTRY`（拿來判斷是否屬於 Power Pool 家族）、`--json`（輸出給程式讀）、`--config my.json`（自訂「暫停模擬的區域」提醒，格式 `{"halted_regions": {"MEA": "暫停中"}}`）。

### 5-4. 看懂結果

```
共 5 個表達式：PASS 2、BLOCKED 3、無法判斷 0
第 6 行 BLOCKED：skew = -1 * group_zscore(ts_mean(ts_backfill(subtract(opt40_ivput20, opt40_ivcall40), 60), ...
  ✗ missing_field opt40_ivcall40：USA/TOP3000/D1 沒有這個欄位
```

| 標記 | 意思 | 怎麼辦 |
|---|---|---|
| `✗ missing_field` | 這個區沒有這個欄位（打錯、用了別區的欄位） | 到 catalog 裡找正確名稱 |
| `✗ removed_field` | 上次匯出還在，這次不見了（下架） | 換欄位 |
| `✗ vector_without_vec_op` | VECTOR 欄位沒先用 `vec_*` 包起來 | 改成 `vec_avg(欄位)`、`vec_sum(欄位)` 等 |
| `✗ unknown_operator` | 你帳號的運算子清單沒有這個運算子 | 換運算子 |
| `✗ wrong_arity`／`unbalanced_parens` | 參數個數不對、括號不成對 | 照提示修 |
| `✗ unfilled_placeholder` | template 的 `<佔位符>` 沒給值 | 補 gene_pool |
| `!` 開頭 | 只是提醒，不擋 | 自己判斷 |

結束代碼：**0** 可以送、**1** 有會擋的問題、**2** 無法判斷（例如沒匯出那個區）。

### 5-5. 接在自己的排隊程式前面

```bash
python gate.py batch.json --region USA --universe TOP3000 --catalog catalog/ && python my_submit_batch.py batch.json
```

`gate.py` 回 1 的時候，後面的送出就不會執行。

更多細節：[`security_gate/README.md`](security_gate/README.md)

---

## 6. Alpha 囤貨婆：一步一步用

### 6-1. 複製設定檔，改成你的條件

```bash
cd inventory_keeper
cp config.example.json config.json
```

**裡面的值是作者的個人設定，不是規定。** 最常需要改的幾項：

| 設定 | 作者的值 | 什麼時候改 |
|---|---|---|
| `corr_max` | 0.7 | 想讓庫存更分散就調低（例如 0.6） |
| `turnover_max` | 0.20 | 你能接受更高換手就放寬；設 `null` 不檢查 |
| `bonus_priority` | 2026 Q4 台灣挑戰賽（USA/GLB、Sharpe>2、Fitness>1、到 12/06） | 沒參加比賽就把 `enabled` 設 `false`；有別的比賽就改成那個比賽的條件 |
| `submit_tiers` | 繳完剩 ≥30 繳 4、≥20 繳 3、≥10 繳 2 | 庫存少的人改成 `[]`，每天就只繳排第一的那支 |
| `score_weights` | Sharpe、Fitness 各 1，prod −2…… | 你更在意哪個指標就把它的權重調大 |

每一項的完整說明：[`inventory_keeper/README.md`](inventory_keeper/README.md)

### 6-2. 列出你的候選

建一個 `ids.txt`，一行一個你覺得「可以繳」的 alpha id（已經模擬過、檢查全過的）：
```
abcd1234
efgh5678
```

### 6-3. 匯出資料

```bash
python brain_export.py --session-pickle ../session.pkl --ids ids.txt --out my_data --recent-days 14
```

它會抓：本季每格 pyramid 已繳幾支和乘數、每支候選的 /check 結果（PROD、SELF、落在哪幾格）和每日 PnL、最近 14 天你繳掉的 alpha 的 PnL（拿來檢查候選會不會跟它們打架）。

### 6-4. 問囤貨婆

```bash
python keeper.py --config config.json --data my_data
```

### 6-5. 看懂結果

| 區塊 | 意思 |
|---|---|
| `庫存 N 支（能補格子 a、格子已滿 b）` | 現在能繳的總數；「格子已滿」的繳了不會多解 pyramid |
| `【今天繳 N 支】` | 照優先序排好的今天要繳的；數量照「繳完還剩幾支」的級距決定 |
| `① 能補滿格子` | 繳了它，某一格本季就能湊滿 3 支 |
| `② 加分條件` | 符合你在 `bonus_priority` 設的條件 |
| `【排隊中】` | 明天以後的順序 |
| `【先留著】` | 格子已滿，繳了不多解 pyramid |
| `【作廢】` | 跟庫存裡分數更高的、或最近才繳的 alpha 每日 PnL 相關太高，繳了一定 SELF FAIL |
| `【下一輪研究】去補` | 還差幾支就能補滿的格子（附乘數），下一輪往這裡找 |
| `【下一輪研究】別再做` | 本季已滿、庫存卻還有同格的，再找到也不會多解 pyramid |

**每一支繳之前，請再到平台打一次 /check，PASS 才繳。** 庫存資料是你匯出當下的快照。

### 6-6. 沒有 session 也能用

自己準備 `my_data/` 裡的檔案就好（`pyramid.json`、`candidates.json`、`pairs.json` 或 `pnl/`），格式見 [`inventory_keeper/README.md`](inventory_keeper/README.md#資料格式自己準備時)，或照著 `example_data/` 的樣子做。

---

## 7. 搭配 Claude Code（或其他 AI）

兩個程式本身就能獨立用；搭配 AI 時，AI 只負責「跑指令、把結果講成白話、照原因改檔」，判斷全部在程式裡。

把各自 README 裡的 prompt 貼進你的 `CLAUDE.md`（或 skill）：
- 安檢門：[`security_gate/README.md` 的「用 Claude Code 當安檢員」](security_gate/README.md#用-claude-code或其他-ai當安檢員)
- 囤貨婆：[`inventory_keeper/README.md` 的「用 Claude Code 當囤貨婆」](inventory_keeper/README.md#用-claude-code或其他-ai當囤貨婆)

之後就可以直接問：「這批可以送嗎？」「今天繳哪幾支？」

---

## 8. 常見問題

**Q：出現「登入過期（401）」？**
重新登入，重存 `session.pkl` 再跑。

**Q：囤貨婆說某支「/check：PROD PENDING」，不收它？**
平台還在算 /check，會回空白。過幾分鐘重新匯出就好。（作者實測一次匯出 3 支，有 2 支遇到這個情況。）

**Q：`catalog_export.py` 跑很久？**
正常。平台對 `/data-fields` 有每分鐘次數限制，程式故意每 3 秒才問一次；欄位多的區第一次可能要幾十分鐘。

**Q：為什麼欄位剛好 10,000 個？**
平台的欄位計數最多只顯示到 10,000。程式碰到上限會改成逐個 dataset 抓（作者實測 GBR/TOP700 實際有 18,294 個）。如果你看到剛好 10,000，代表用的是舊版，請更新。

**Q：安檢門說 PASS，模擬還是失敗？**
安檢門只擋「清單查得到的錯」。平台端臨時失敗、資源不足（例如太重的運算）它擋不到。

**Q：安檢門顯示「無法判斷」？**
多半是沒匯出那個 region/universe/delay 的清單，或是 Python `@alpha` template（目前只檢查 FastExpr）。

**Q：囤貨婆說「缺 PnL」或「查不到相關」？**
相關性要用每日 PnL 算；PnL 抓不到、或兩支共同交易日少於 60 天，就當作「不知道」，那支先不入庫（不猜）。

---

## 9. 怎麼確認它們是對的

兩個程式都是從作者正式在跑的系統抽出來的，並用同一份資料逐項比對過（2026-11-25）：

| 項目 | 結果 |
|---|---|
| 安檢門 vs 正式系統：正式擋下的 19 批 | 分享版也全擋，擋的原因逐項相同 |
| 安檢門 vs 正式系統：正式放行的 59 批 | 分享版也全放行，沒有誤擋 |
| 安檢門欄位匯出：GBR/TOP700/D1 | 18,294 個欄位，與正式每日同步的清單完全相同 |
| 囤貨婆 vs 正式系統：33 支候選 | 判定、優先序、分數 0 差異 |
| 囤貨婆範例輸出 | 用 `example_data/` 跑，跟投稿文第四節逐字相同 |

---

## 10. 版本、授權、回報問題

| 版本 | 日期 | 內容 |
|---|---|---|
| v1.0 | 2026-11-25 | 第一版。規則對應作者正式系統 2026-11-24 的版本（入庫規則、繳交排序、margin 加減分、模擬前檢查），並逐項比對過結果一致。 |

作者正式系統的規則有改動時，會同步更新這裡並加新版本。

- **授權**：MIT，歡迎拿去改成自己的版本。
- **回報問題**：在 GitHub 開 Issue，或到論壇投稿文底下留言。
