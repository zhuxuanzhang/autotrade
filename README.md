# AutoTrade · A 股策略研究与模拟交易看板

基于 Python 的本地 A 股行情、选股、历史回测和模拟交易工具，提供浏览器看板，查看买卖信号、持仓、交易日历和收益记录。项目不连接券商，不提交真实订单。

## 主要功能

- 通过 AKShare 等行情接口获取股票历史数据，保存本地快照并复用缓存。
- 结合突破、成交量、历史回撤、价格区间及市场条件计算买卖信号。
- 持久化模拟账本、日报和 SQLite 交易记录，按日期查看交易与持仓。
- 提供历史回测及量能、突破、退出条件等对比脚本。
- 使用本地 HTTP 服务展示网页，无需 Node.js 或前端构建步骤。

## 环境准备

当前运行环境为 **Windows + Python 3.12**。每日更新、盘中采集和部分迁移脚本使用 Windows 的 `msvcrt` 文件锁，尚不能直接作为跨平台应用运行。

在 PowerShell 中执行：

```powershell
git clone https://github.com/zhuxuanzhang/autotrade.git
cd autotrade
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install akshare pandas numpy requests
New-Item -ItemType Directory -Force data, reports | Out-Null
```

上述安装命令根据源码的直接依赖整理；仓库暂未提供锁定版本的依赖清单，不能保证不同安装时间的依赖行为完全一致。已有本地 `.python` 环境的用户也可以继续使用 `.\.python\python.exe`。

以下命令均在仓库根目录执行。行情下载与风险名单刷新需要联网。

## 数据准备

**本仓库只发布代码与文档，不包含行情、模拟账本、历史回放和回测结果。** 新克隆目录不能直接还原原电脑的完整看板。

下载默认历史行情快照：

```powershell
.\.venv\Scripts\python.exe download_history.py --workers 2
```

默认截止日期为 `20261114`，输出到 `data/a_share_20261114/`。下载器会跳过已有 CSV 与元数据完整的文件；不要同时启动多份下载任务。只想小范围检查下载流程时可加 `--limit 10`，这不构成全市场数据。

可通过 `--end YYYYMMDD` 下载其他截止日期的独立快照，但现有看板与部分回测脚本仍固定读取 `data/a_share_20261114/daily_hfq/`，不会自动切换到新目录。

完整交易日历还依赖本地历史回放文件：`unified_records.py` 默认读取 `experiments/current_rules_2026_20261116/daily/`；若存在 `data/daily_signals/history_view.json`，则按其中的 `daily_path` 读取。恢复已有部署时，需要同时恢复相应历史回放、结果目录和 `data/daily_signals/`。跨电脑恢复后应核对配置中的路径。

历史实验目录整体未纳入 Git，仓库未提供完整回放档案的一键初始化流程。缺少这些文件时，部分看板接口及每日更新末尾的记录重建会报错；仅下载行情无法补齐历史回放档案。

## 启动看板

```powershell
.\.venv\Scripts\python.exe dashboard_server.py
```

打开 [本地看板](http://127.0.0.1:8765) 或 [每日交易页面](http://127.0.0.1:8765/daily)。服务仅监听 `127.0.0.1:8765`；页面操作也校验该地址，请使用这个地址访问。按 `Ctrl+C` 停止服务。

## 常用命令

仅拉取、更新行情，不重算策略：

```powershell
.\.venv\Scripts\python.exe daily_signals.py --update --pull-only
```

在本地历史档案准备完整后，更新行情并计算每日模拟交易：

```powershell
.\.venv\Scripts\python.exe daily_signals.py --update
```

使用本地个股行情计算策略（交易日与风险名单过期时仍可能联网刷新）：

```powershell
.\.venv\Scripts\python.exe daily_signals.py
```

运行历史基础回测：

```powershell
.\.venv\Scripts\python.exe backtest.py --start 2016-01-01 --end 2026-11-13
```

基础回测读取默认历史快照，结果输出到 `reports/backtest_exit_0.92/`。它与每日模拟交易使用不同的执行流程，不应将其结果直接视为当前每日规则的完整重放。其他 `compare_*.py` 脚本用于各类参数对比。

自动定时任务不随 Git 仓库安装；需要按本机环境另外配置。`fix_*`、`apply_*`、`activate_*` 等脚本属于已有数据的修复或迁移工具，不是首次安装步骤，部分包含原机器路径。

## 模拟交易口径

当前每日规则按日期版本化，具体以 `daily_signals.py` 的 `rules_for_day()` 及相关过滤模块为准。有效盘中快照用于锁定信号，模拟买入按当日有效收盘价记录；缺少有效盘中快照时使用收盘兜底信号。模拟卖出按触发日收盘执行，并禁止买入当天卖出。

每笔模拟 100 股，不设账户资金或总仓位约束；买卖各按 0.2% 估算综合成本。后复权价格用于收益估算，展示成交价使用未复权价格。因此统计是独立交易研究结果，不是实际账户收益。数据源差异、缺失行情、历史样本的幸存者偏差均会影响结果。

## 目录说明

| 路径 | 用途 | 纳入 Git |
| --- | --- | --- |
| `dashboard/`、`dashboard_server.py` | 网页与本地服务 | 是 |
| `daily_signals.py`、`right_side.py`、过滤模块 | 每日信号与策略逻辑 | 是 |
| `backtest.py`、`compare_*.py` | 基础回测与对比脚本 | 是 |
| `test_*.py` | 测试代码 | 是 |
| `data/` | 行情、风险名单、账本、日报、数据库 | 否 |
| `数据/` | 本地数据及中文命名的回测档案 | 否 |
| `experiments/` | 本地实验、历史回放及备份，包含该目录内的脚本 | 否 |
| `reports/` | 生成的报告、图像和回测产物 | 否 |
| `.python/`、`.venv/` | 本地 Python 环境 | 否 |

日志、进程文件、Python 缓存和本地环境配置也由 `.gitignore` 排除。忽略规则不会删除本地文件，也不能替代数据备份；特别是 `data/daily_signals/ledger.json`，不要随意删除或重置。

数据来源、原始快照说明与历史规则记录见 [DATA_README.md](DATA_README.md)。
