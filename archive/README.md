# archive/ - 历史归档目录

> **警告：本目录中的脚本仅供参考，禁止直接执行**

## 说明

本目录存放已废弃的临时脚本和过时文档，保留用于历史追溯。

## 文件清单

| 文件 | 原用途 | 废弃原因 |
|------|--------|----------|
| `backfill_eai_logs.py` | 历史数据补录（旧版） | 已被 `backfill_fixed.py` 替代 |
| `fix_acc_erp_report_20260302.py` | 2026-03-02 一次性数据修复 | 已执行完毕 |
| `fix_erp_report_20260302.py` | 2026-03-02 补录4条丢失记录 | 已执行完毕 |
| `DEPLOY_20260112.md` | 2026-01-12 部署说明 | 路径已过时，参见 `docs/deploy.md` |
| `DEPLOY_COMMANDS.txt` | 初始部署命令 | 路径已过时，参见 `docs/deploy.md` |
| `DEPLOY_GUIDE.md` | 部署指南 | 已合并到 `docs/deploy.md` |
| `start.bat` | 手动启动脚本 | 服务已注册为 Windows 服务，用 `sc` 管理 |
| `start_production.bat` | 生产启动脚本 | 同上 |
| `start.sh` | Linux 启动脚本 | 生产环境为 Windows，不适用 |
| `deploy_to_165.bat` | 早期 BAT 部署脚本 | 已被 `scripts/deploy.ps1` 替代 |

## 规范

- 不得从此目录执行任何脚本
- 不得修改此目录中的文件
- 如需参考历史逻辑，阅读即可
