# etf-flows · 行业ETF资金流数据仓

每个交易日自动更新的 A股 / 美股 行业ETF 资金净流入数据（只出 JSON，展示在个人主页）。

## 输出（schema_version 1）
- A股：https://raw.githubusercontent.com/newmymujian-hash/etf-flows/main/data/cn.json
- 美股：https://raw.githubusercontent.com/newmymujian-hash/etf-flows/main/data/us.json

单位：金额为货币原值（元 / 美元），份额为"份"原值。

## 口径
- 当日净流入 = (T日份额 − T−1日份额) × T日单位净值；份额拆分/合并日记为 null 并标注 corporate_action
- A股份额：上交所、深交所ETF规模公告，T日收盘口径（深交所以T+1早间更新值为准）；净值：东方财富
- 美股：State Street (SSGA) 每日 NAV 与份额；SMH 来自 VanEck（份额 = AUM / NAV）
- data_date = 份额所属交易日

## 维护
- 行业与ETF清单：`config/industries.json`
- 抓数与计算：`scripts/update.py`（`--build-only` 只用已存原始数据重算）
- 定时：`.github/workflows/daily.yml`，北京时间 T+1 日 09:30；也可在 Actions 页手动运行
- 更新失败时保留上一份成功的 JSON

数据为自行计算的估计值，仅供参考，不构成投资建议。
