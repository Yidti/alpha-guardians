# Alpha 守門雙俠（Alpha Guardians）

WorldQuant BRAIN 顧問用的兩個小幫手，2026 Q4 Local Agent Challenge 投稿作品。

| | 守在哪 | 做什麼 | 資料夾 |
|---|---|---|---|
| 🚪 **Alpha 安檢門** | 送模擬**之前** | 把一定會報錯的表達式先擋下來：欄位不存在、VECTOR 沒包 `vec_*`、參數個數不對……不花模擬額度 | [`security_gate/`](security_gate/) |
| 🧺 **Alpha 囤貨婆** | 繳交**之前** | 好 alpha 先囤著：每天決定繳哪幾支、哪些先留、哪些會互相打架而作廢，並告訴你下一輪去補哪一格 pyramid | [`inventory_keeper/`](inventory_keeper/) |

- 只用 Python 標準函式庫（3.9 以上），不用裝套件。
- **不呼叫 simulation API、不會幫你繳交。** 匯出程式只做唯讀 GET，需要你自己已登入的 `requests.Session`。
- 所有門檻都是作者的個人設定，請照自己的條件改（各資料夾的 README 有說明）。
- 兩個都跟作者正式系統的結果逐項比對過：安檢門擋 19/19、放行 59/59 一致；囤貨婆 33 支候選判定 0 差異。

## 快速試跑（不用登入）

```bash
# 囤貨婆：用附的範例資料（真實數據，alpha ID 已換成假名字）
cd inventory_keeper
python keeper.py --config config.example.json --data example_data --today 2026-11-25
```

安檢門需要先用 `catalog_export.py` 匯出你帳號的欄位清單才能檢查，見 [`security_gate/README.md`](security_gate/README.md)。

## 授權

MIT，歡迎拿去改成自己的版本。
