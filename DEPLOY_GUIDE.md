# EAI日志监听服务 - 165服务器部署指南

## 快速部署步骤

### 方式一：通过共享文件夹部署（推荐）

1. **建立网络连接**
   ```cmd
   net use \\172.17.10.165\d$ /user:administrator [密码]
   ```

2. **创建目标目录**
   ```cmd
   mkdir \\172.17.10.165\d$\eai_log_monitor
   ```

3. **复制文件**
   ```cmd
   robocopy "D:\TechTeam\Delivery\ACC运维\eai_log_monitor" "\\172.17.10.165\d$\eai_log_monitor" config.py log_parser.py db_handler.py eai_log_monitor.py requirements.txt README.md /XD __pycache__
   copy "D:\TechTeam\Delivery\ACC运维\eai_log_monitor\start_production.bat" "\\172.17.10.165\d$\eai_log_monitor\start.bat"
   copy "D:\TechTeam\Delivery\ACC运维\eai_log_monitor\install_service.bat" "\\172.17.10.165\d$\eai_log_monitor\"
   ```

4. **远程登录165服务器执行后续步骤**

---

### 方式二：远程桌面手动部署

1. 使用远程桌面连接到 `172.17.10.165`
2. 在165服务器上创建目录 `D:\eai_log_monitor`
3. 从本地复制以下文件到165服务器：
   - config.py
   - log_parser.py
   - db_handler.py
   - eai_log_monitor.py
   - requirements.txt
   - start_production.bat (重命名为 start.bat)
   - install_service.bat
   - README.md

---

## 165服务器配置步骤

### 1. 确认Python环境

```cmd
python --version
```

如果未安装Python，从 https://www.python.org/downloads/ 下载安装Python 3.8+

### 2. 安装依赖包

```cmd
cd D:\eai_log_monitor
pip install -r requirements.txt
```

### 3. 确认Oracle Instant Client

165服务器作为ACC数据库服务器，应该已安装Oracle客户端。

验证：
```cmd
python -c "import cx_Oracle; print(cx_Oracle.version)"
```

如果cx_Oracle未安装或报错，执行：
```cmd
pip install cx_Oracle
```

如果报Oracle客户端错误，需要：
1. 下载Oracle Instant Client: https://www.oracle.com/database/technologies/instant-client.html
2. 解压到如 `C:\oracle\instantclient_21_9`
3. 添加到系统PATH环境变量
4. 重启命令行

### 4. 测试连接

```cmd
cd D:\eai_log_monitor
python test_connections.py
```

这将测试：
- SSH连接到EAI服务器(172.17.10.163)
- Oracle连接到本地数据库

### 5. 启动服务

**手动启动**（测试）：
```cmd
cd D:\eai_log_monitor
start.bat
```

**注册为Windows服务**（生产推荐）：
```cmd
cd D:\eai_log_monitor
install_service.bat
```

---

## 验证部署

### 1. 查看服务状态

如果注册为服务：
```cmd
nssm status EAILogMonitor
```

或打开 `services.msc` 查找 "EAI日志监听服务"

### 2. 查看日志

```cmd
type D:\eai_log_monitor\eai_monitor.log
```

或实时查看：
```cmd
powershell Get-Content D:\eai_log_monitor\eai_monitor.log -Wait
```

### 3. 查看数据库记录

```sql
SELECT * FROM ACC_ERP_REPORT_SUCCESS ORDER BY CREATE_TIME DESC;
```

---

## 配置说明

### 环境变量

| 变量 | 说明 | 生产环境值 |
|------|------|-----------|
| EAI_MONITOR_ENV | 运行环境 | production |

### 网络连接

| 连接 | 地址 | 端口 | 说明 |
|------|------|------|------|
| EAI服务器 | 172.17.10.163 | 2200 | SSH连接读取日志 |
| ACC数据库 | 172.17.10.165 | 1521 | Oracle数据库(本机) |

---

## 故障排查

### SSH连接失败

```cmd
REM 测试网络
ping 172.17.10.163

REM 测试端口
powershell Test-NetConnection -ComputerName 172.17.10.163 -Port 2200
```

### 数据库连接失败

```cmd
REM 165是数据库服务器，应该可以本地连接
sqlplus iplant_dpepp1/acc@172.17.10.165:1521/orcl.ecdag.com
```

---

## 部署完成检查清单

- [ ] 文件已复制到 `D:\eai_log_monitor`
- [ ] Python 3.8+ 已安装
- [ ] 依赖包已安装 (paramiko, cx_Oracle)
- [ ] Oracle Instant Client 已配置
- [ ] 测试连接成功
- [ ] 服务已启动
- [ ] 日志正常输出
- [ ] 数据库有新记录

---

## 联系支持

- 技术支持：韩大师 (ACC运维专家)
- 部署日期：2026-01-11
