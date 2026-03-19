# EAI日志监听服务

> 本服务是[工单小管家](https://github.com/dtrongjet790627/WorkOrderHelper)的配套工具，负责实时监听EAI接口日志并将报工记录同步至ACC数据库。

---

## 目录结构与文件规范

```
eai_log_monitor/
│
├── 【核心服务文件】（禁止随意修改，修改前必须停服备份）
│   ├── eai_log_monitor.py      主程序：SSH监听 + 数据处理循环
│   ├── log_parser.py           日志解析：正则提取报工字段
│   ├── db_handler.py           数据库层：Oracle写入/去重
│   ├── config.py               配置：SSH/DB连接信息
│   └── backfill_fixed.py       补录工具：历史数据批量导入
│
├── requirements.txt            Python依赖
├── README.md                   本文档
├── .gitignore                  忽略 *.log __pycache__ 等
│
├── docs/                       文档目录
│   └── 操作规范.md             服务运维手册（服务信息/排查/规范）
│
├── scripts/                    运维脚本目录
│   ├── deploy.ps1              部署脚本（停服→复制→启服）
│   └── install_service.bat     Windows服务注册（首次部署用）
│
├── tools/                      调试工具目录（生产环境不部署）
│   ├── test_connections.py     测试SSH/Oracle连接
│   └── verify_backfill.py      验证补录结果
│
└── archive/                    历史归档（只读，禁止执行）
    ├── README.md               归档说明
    ├── backfill_eai_logs.py    旧补录脚本（已废弃）
    ├── fix_*_20260302.py       2026-03-02一次性修复脚本
    ├── DEPLOY_*.md / .txt      过时部署文档
    └── start*.bat / start.sh   旧启动脚本
```

### 目录使用规范

| 目录 | 用途 | 规范 |
|------|------|------|
| 根目录 | 服务运行必需文件 | 只放核心服务文件，不得随意新增 |
| `docs/` | 文档 | 操作规范、设计说明等 |
| `scripts/` | 可执行运维脚本 | 仅放部署/安装类脚本 |
| `tools/` | 调试工具 | 开发排查用，不部署到生产 |
| `archive/` | 历史归档 | 只读，不可修改，不可执行 |

> **禁止在根目录创建临时脚本**（如 `fix_xxx.py`、`test_xxx.py`）。临时脚本执行完毕后移入 `archive/`；调试工具放入 `tools/`。

---

## 功能说明

通过SSH连接EAI服务器，`tail -F` 实时监听多条产线日志，解析报工请求/响应对，将结果写入ACC Oracle数据库。

### 产线与数据库映射

| 日志文件（EAI 163服务器） | 产线 | Schema（165数据库） |
|--------------------------|------|-------------------|
| `FLOW_SMT/SMT-Line1MES报工接口.log` | SMT Line1 | iplant_dpepp1 |
| `FLOW_SMT/MID-Line2MES报工接口.log` | SMT Line2 | iplant_smt2 |
| `FLOW_DP-EPS/IPA MES报工接口.log` | DP-EPS IPA | iplant_dpeps1 |

---

## 快速操作

### 查看服务状态
```powershell
ssh Administrator@172.17.10.165 "sc query DT.TechTeam_EAI_Log_Monitor"
```

### 重启服务
```powershell
ssh Administrator@172.17.10.165 "sc stop DT.TechTeam_EAI_Log_Monitor"
ssh Administrator@172.17.10.165 "sc start DT.TechTeam_EAI_Log_Monitor"
```

### 部署更新
```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy.ps1
```

### 查看运行日志
```powershell
ssh Administrator@172.17.10.165 "powershell Get-Content D:\CustomApps\eai_log_monitor\eai_monitor.log -Tail 50"
```

---

## 历史数据补录

```bash
# 仅解析预览（不写入）
python backfill_fixed.py --start-date 2026-01-01 --dry-run

# 补录指定schema
python backfill_fixed.py --start-date 2026-01-01 --schema smt2

# 补录全部
python backfill_fixed.py --start-date 2026-01-01
```

---

## 环境信息

| 项目 | 内容 |
|------|------|
| 服务服务器 | 172.17.10.165 |
| 服务路径 | `D:\CustomApps\eai_log_monitor\` |
| 服务名 | `DT.TechTeam_EAI_Log_Monitor` |
| EAI日志服务器 | 172.17.10.163:2200 |
| 数据库 | 172.17.10.165:1521/orcl.ecdag.com |
| Python | `C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe` |

详细操作规范见 [docs/操作规范.md](docs/操作规范.md)。
