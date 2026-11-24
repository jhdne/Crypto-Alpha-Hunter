# Crypto Alpha Hunter V7.0

全周期加密 Alpha 自动化捕获、多维交叉验证与类脑自进化投研系统，支持一键部署至 GitHub Actions + GitHub Pages 24/7 自动运行。

## 核心特性

1. **全周期 Alpha 捕获与前瞻配置**
   - **热点狙击 (`job2_project_hunter.py`)**：并发扫描 GeckoTerminal (`new_pools` / `trending_pools`) 与 DexScreener (`token-boosts` + 热词搜索)，毫秒级捕捉刚启动的低市值点火标的，内置防追高与防刷单过滤。
   - **价值挖掘与基本面穿透**：集成 CoinGecko 基本面数据（`MC/FDV` 流通率、距 ATH 回撤、GitHub 4 周代码提交量）与 DeFiLlama 一级市场融资/TVL 资金面，锁定高确定性价值击球区。
   - **趋势推演与配置清单 (`job1_track_finder.py`)**：自动研判升温赛道，为每个重点赛道输出 **龙头标的 (Leader)** 与 **黑马标的 (Dark Horse)** 配置建议。
2. **类脑级自主进化引擎 (`llm_engine.py` + `job3_self_evolver.py`)**
   - **多空并行辩论投委会**：`Bull Agent`（多头猎手）与 `Bear Agent`（空头风控）并行推演，再由 `CIO Judge` 结合进化纪律终审并给出仓位与止盈止损建议。
   - **胜率 + 盈亏比策略归因**：每 4 小时批量回测推荐池实时价格、峰值涨幅（MFE）与最大回撤（MAE），计算胜率、盈亏比（Payoff Ratio）与期望收益（Expectancy），动态进化风控阈值与五维评分权重。
3. **多维全景交叉验证与合约排雷**
   - 聚合链上量价、热搜舆情、VC 融资/TVL 资金面与免费合约安全审计（GoPlus EVM / RugCheck Solana），拦截貔貅盘与高税率合约，输出可信度评级。

## 快速部署到 GitHub

1. 将本仓库推送至你的 GitHub 仓库。
2. 在仓库 **Settings -> Pages** 中将 Source 设置为 `Deploy from a branch`，分支选择 `main`、目录选择 `/docs`。
3. 在 **Settings -> Secrets and variables -> Actions** 中按需添加密钥（参考 `.env.example`，即使全部留空也可通过本地量化引擎运行）。
4. 进入 **Actions** 页面手动触发 `Crypto Alpha Hunter 24H` 工作流即可完成首次扫描并生成看板。

## 本地运行与测试

```bash
pip install -r requirements.txt
python preflight_check.py
python -m unittest discover -s tests -v
python job1_track_finder.py
python job2_project_hunter.py
python notifier.py
```
