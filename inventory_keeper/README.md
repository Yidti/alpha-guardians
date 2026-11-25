# Alpha 囤貨婆（Alpha Hoarder）

每天回答兩件事：
1. **今天繳哪幾支、哪些先留、哪些作廢**
2. **下一輪研究去補哪一格、哪一格別再做**

> ⚠️ **裡面的門檻是我個人的設定，不是規定。** 相關上限、換手上限、一天繳幾支、要不要為某個比賽加分……
> 全部寫在 `config.json`，請照你自己的庫存條件改（見下面「怎麼改成你的條件」）。

- 只用 Python 標準函式庫（3.9 以上），不用裝任何套件就能跑 `keeper.py`。
- 不呼叫 simulation API、不會幫你繳交。`brain_export.py` 只做唯讀 GET。
- 在我自己的資料上，跟我正式系統的判定逐支比對：33 支候選 **0 差異**（2026-11-25）。

## 三步驟

```bash
# 1. 複製設定，照你的條件改
cp config.example.json config.json

# 2. 從平台匯出資料（需要你自己已登入的 requests.Session，例如 open machine 的 session.pkl）
#    ids.txt：你覺得能繳的候選 alpha id，一行一個
python brain_export.py --session-pickle session.pkl --ids ids.txt --out my_data --recent-days 14

# 3. 問囤貨婆
python keeper.py --config config.json --data my_data
```

沒有 session 也可以自己準備 `my_data/` 的檔案（格式見最後一節）。
先用 `example_data/` 試跑（我 11/25 的真實數據，alpha ID 已換成 cand01、sub01 這類假名字；sub 開頭的是「最近才繳的」）：`python keeper.py --config config.example.json --data example_data --today 2026-11-25`

## 它怎麼判斷（照順序）

1. **進不進庫存**：平台 /check 的 PROD、SELF 都要 PASS；換手不能超過你的上限；要知道落在哪一格。
2. **會不會打架**：候選依分數由高到低排，跟已經入庫的任一支每日 PnL 相關 ≥ 上限 → 分數低的作廢。
   跟「最近才繳的 alpha」打架的也作廢（平台算 SELF 時還沒算到它們）。
3. **格子滿了沒**：那格「本季已繳＋庫存同格」還不到滿格數 → 入庫（能補格子）；已滿 → 保留區（仍是庫存，只是繳了不多解 pyramid）。
4. **繳交優先序**：① 繳了補得滿某一格 → ② 你設的加分條件（例如比賽）→ 一般（格子補不滿）→ 暫不繳（格子已滿）。
   同一級裡：繳了剛好讓某格滿的先 → prod 偏高但 /check 判 PASS 的（邊緣，放久了可能翻 FAIL）先 → 分數高的先。
5. **今天繳幾支**：看「繳完還剩幾支」對照你的級距表。
6. **研究方向**：庫存補不滿的格子、已繳 1～2 支但庫存沒有的格子（照還差幾支、乘數排）、已滿但庫存還一直進來的格子（別再做）。

## 怎麼改成你的條件（config.json）

| 設定 | 我的值 | 意思 | 什麼時候該改 |
|---|---|---|---|
| `corr_max` | 0.7 | 庫存之間 PnL 相關上限 | 想讓庫存更分散就調低，例如 0.6 |
| `cell_full` | 3 | 一格幾支算滿 | 平台規則變了才改 |
| `turnover_max` | 0.20 | 換手上限；`null` 不檢查 | 你能接受高換手就放寬或設 null |
| `require_check_pass` | true | PROD／SELF 都要 /check PASS | 建議不要關 |
| `edge_prod` | 0.7 | prod ≥ 這個數但 /check PASS 的算「邊緣」，排前面先繳 | — |
| `score_weights` | 見檔案 | 分數＝各指標×權重加總 | 你比較在意 Fitness 就把 fitness 權重調高；不想看 margin 就把 margin 設 0 |
| `bonus_priority` | USA/GLB、Sharpe>2、Fitness>1、到 12/06 | 你自己的「優先②」條件（例如某個比賽） | 沒參加比賽就 `"enabled": false` |
| `submit_tiers` | 剩≥30 繳4、≥20 繳3、≥10 繳2 | 繳完還剩幾支 → 今天繳幾支 | 庫存少的人建議改成 `[[5, 2]]`、`default_submit: 1` |
| `max_submit_per_day` | 4 | 一天最多幾支 | 照平台當期上限 |
| `research.top_n` | 5 | 研究建議列幾格 | — |

**庫存很少的人（例如手上只有 1～3 支）**：囤貨婆一樣有用。重點會變成「這支繳了會不會多解一格」和「下一輪去哪格」，
把 `submit_tiers` 改成 `[]`、`default_submit` 設 1，就是每天繳排第一的那支。

## 用 Claude Code（或其他 AI）當囤貨婆

把這段放進你的 `CLAUDE.md` 或 skill（跟投稿文第三節是同一份）：

```
你是「Alpha 囤貨婆」。研究員找到、驗證過的 alpha 先放進庫存；你每天決定繳哪幾支、留哪幾支、
哪幾支作廢，並告訴研究員下一輪去補哪一格。

【每天的流程】
1. 跑 python brain_export.py --session-pickle session.pkl --ids ids.txt --out my_data --recent-days 14
2. 跑 python keeper.py --config config.json --data my_data
3. 照 keeper.py 的輸出用白話回答，先講結論：今天繳哪幾支（附理由）、哪些先留、哪些作廢、
   下一輪研究哪幾格。每個建議都附上數字。

【你不能做的事】
- 不要自己繳交（兩段式繳交）：每一支繳之前再打一次平台 /check，PASS 才繳；
  先把數字給我看，我說可以才繳。不准驗完立刻繳。
  （起因：11/15 資料庫標「可繳」的 3 支，平台現查 2 支早就被繳過、1 支還沒算完。）
- 不要自己改 config.json 的門檻；覺得不合理就提出來問我。
- keeper.py 判斷不了的（資料不夠、/check 還在算）照實說，不猜。

【keeper.py 照順序套用的規則（括號內是我的設定值，都在 config.json）】
1. 進不進庫存：平台 /check 的 PROD、SELF 都要 PASS；換手 ≤ 上限（20%）；要知道落在哪一格。
   prod ≥ 0.7 但 /check 判 PASS 的算「邊緣」，同一級裡排前面先繳。
   （起因：11/21 sub16 入庫時 prod 0.7346 判 PASS，放 2 天沒繳，繳交當下平台改判 FAIL。）
2. 會不會打架：依分數由高到低，跟已入庫的任一支每日 PnL 相關 ≥ 上限（0.7）→ 分數低的作廢；
   跟「最近才繳的 alpha」相關 ≥ 上限的也作廢。
   （起因：11/17 hist01 與 hist02 相關 0.718 同時在庫存，繳一支另一支就廢。）
3. 分數 = Sharpe + Fitness + 0.5×近兩年較差那年 Sharpe − 2×prod − self − 2×換手 ± margin 加減分。
4. 繳交優先序：
   ① 能補滿格子：那格「本季已繳＋庫存同格」≥ 3。
   ② 加分條件（我設的是本季台灣挑戰賽：USA/GLB、Sharpe > 2、Fitness > 1，12/06 前）。
   一般：可以繳，但那格補不到 3 支。
   暫不繳：那格本季已滿 3 支，繳了不多解 pyramid。
   同一級裡：繳了剛好讓某格滿 3 支的先 → 邊緣的先 → 分數高的先。
   （起因：本季有 28 支繳進了已滿的格子。）
5. 今天繳幾支：看「繳完還剩幾支」——剩 ≥ 30 繳 4 支、≥ 20 繳 3 支、≥ 10 繳 2 支，否則 1 支。
   （起因：以前驗完就繳，庫存永遠只有 0～4 支，哪天沒找到就沒東西可繳。）
6. 研究方向：庫存補不滿 3 支的格子、已繳 1～2 支但庫存沒有的格子 → 去補；
   本季已滿、庫存卻還有同格的 → 別再做。
```

## 資料格式（自己準備時）

`pyramid.json`：本季每格已繳幾支
```json
[{"cell": "USA/D1/NEWS", "submitted": 0, "multiplier": 1.2}]
```

`candidates.json`：候選（`cells` 用 /check 的 MATCHES_PYRAMID 給的格子；`margin` 是比例，0.0015＝15 bps）
```json
[{"alpha_id": "abc123", "region": "USA", "cells": ["USA/D1/NEWS", "USA/D1/OTHER"],
  "sharpe": 2.3, "fitness": 1.6, "turnover": 0.09, "margin": 0.0015,
  "prod_corr": 0.55, "self_corr": 0.2, "prod_check": "PASS", "self_check": "PASS"}]
```

相關性，二選一：
- `pnl/<alpha_id>.csv`：`date,pnl`（累積 PnL），候選和最近才繳的都放；最近才繳的 id 列在 `submitted_after.json`。程式會自己算相關和近兩年逐年 Sharpe。
- `pairs.json`：已經算好的相關 `{"pairs": [["a","b",0.43]], "after_submits": {"a": [["已繳id", 0.91]]}}`。

## 已知限制

- 平台 /check 還在算時會回空白：匯出程式會標 PENDING，囤貨婆先不收它，晚點重匯出就好（實測 11/25 三支裡有兩支遇到）。
- 相關性要有每日 PnL 才算得出來；少於 60 個共同交易日的配對當作「不知道」，那支會先不入庫。
- 優先②（加分條件）只是加分排序，不會把不合格的放進庫存。
- 只在我自己的帳號實測過匯出程式。
