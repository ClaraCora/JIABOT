# JIABOT - 家宽 VPS Telegram 自动化运维机器人

专门为动态家宽（家庭宽带）VPS、NAT VPS 及动态云服务器设计的 Telegram 自动化运维与体检机器人。

已原生预配置适配 **boil.network** 等主流家宽平台 API，支持公网 IP 探测、防误触二次确认更换 IP、以及调用 `xykt/IPQuality` 脚本进行全维度流媒体/AI 解锁与风控体检。

---

## ✨ 核心特性

- 🛡️ **严格的权限控制**：基于 `ALLOWED_USER_IDS` 白名单机制，支持配置多个 Telegram 管理员，非授权用户一律拦截并提示其用户 ID。
- 🌐 **实时公网 IPv4 探测**：优先使用 VPS 服务商接口获取公网 IP，同时配备多权威公网节点（ipify、check.place 等）智能轮询兜底，获取 IP 归属地与 ISP。
- ⚠️ **防误触二次确认更换 IP**：
  - 点击“更换IP”后，弹出专用安全确认菜单与风险警示。
  - 必须显式点击【⚠️ 确认更换 IP】方可提交换 IP 指令，有效防止日常误触导致 VPS 网络中断。
  - 原生适配 `boil.network` 的 POST API (`/api/v1/changeIP/`)，亦支持自定义 HTTP API 或本地重拨命令（如 PPPoE）。
  - 后台异步轮询探测新 IP，网络恢复并获取到新 IP 后自动向管理员推送通知。
- 📊 **集成 `xykt/IPQuality` 质量体检与留存**：
  - **定时自动巡检**：定时在后台调用开源著名的 [xykt/IPQuality](https://github.com/xykt/IPQuality) 脚本进行全方位 IPv4 质量与解锁体检。
  - **秒级查询**：在本地持久化留存最后一次的完整体检报告，用户在 Bot 中查询时秒级展示排版精美的卡片，无需耗时等待。
  - **主动实时测质**：发送 `/test` 或点击【⚡ 立即测质】，立即在 VPS 后台实时运行体检脚本并推送报告。
  - **全维度解析**：自动解析 Scamalytics 欺诈分、AbuseIPDB 滥用率、原生家宽判定、流媒体解锁（Netflix、Disney+、YouTube Premium、TikTok、Amazon）与 ChatGPT 及 25 邮件端口。
  - **原始报告导出**：支持一键导出包含完整细节的 `.txt` 日志文件。
- ⏰ **定时巡检与 IP 意外变动告警**：
  - 支持自定义时间点（默认每天早 09:00 与晚 21:00）自动在后台跑一次体检并推送结果。
  - 心跳机制每 20 分钟检测一次公网 IP，若检测到运营商强制重拨引起的 IP 变动，自动告警并触发新 IP 测质。
- 📜 **历史记录分页与全维度解锁回顾**：
  - 过往的每一次体检记录均详细保留原生 IP、风控分及 Netflix、Disney+、YouTube、ChatGPT、TikTok、AmazonPV、Reddit 等流媒体与 AI 解锁状态。
  - 支持内联分页浏览（每页 4 条）与一键刷新。
- 📱 **双重交互体验**：同时提供底部常驻快捷回复键盘（ReplyKeyboard）与现代化内联操作面板（InlineKeyboard）。

---

## 📱 Bot 指令与功能一览

| 指令 | 说明 | 响应速度 |
| :--- | :--- | :--- |
| `/start` 或 `/menu` | 唤出主控面板与常驻快捷键盘 | 秒级 |
| `/ip` | 实时探测 VPS 当前公网 IPv4 地址与节点归属 | 1~3秒 |
| `/change_ip` | 发起换 IP 流程（弹出二次确认防误触菜单） | 交互菜单 |
| `/test` 或 `/check` | **主动实时体检当前 IP 质量** (实时在 VPS 跑脚本) | 约 30~60 秒 |
| `/quality` 或 `/report` | **查看最后一次留存的体检报告** (读取本地缓存) | **秒级瞬间返回** |
| `/history` | 查看历史记录（含各次 IP 变动与完整解锁，支持翻页） | 秒级 |
| `/help` | 查看详细使用帮助与操作指南 | 秒级 |

---

## 🛠️ 快速安装与配置

### 1. 克隆代码并安装依赖

要求 Python 3.10+ 环境：

```bash
git clone https://github.com/ClaraCora/JIABOT.git
cd JIABOT

# 创建并激活虚拟环境 (推荐)
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

> **注意 (Linux VPS 依赖)**：`xykt/IPQuality` 脚本执行需要 `bash`、`curl`、`jq` 等基础命令行工具。
> Ubuntu/Debian 请运行：`apt-get update && apt-get install -y curl jq dnsutils`
> CentOS/Rocky 请运行：`yum install -y curl jq bind-utils`

---

### 2. 配置环境变量 (`.env`)

复制配置模板：

```bash
cp .env.example .env
nano .env   # 或使用 vim / 任意文本编辑器修改
```

只需填写 3 个核心参数即可：

```env
# 1. Telegram Bot Token (向 @BotFather 申请)
BOT_TOKEN=1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ

# 2. 授权管理员 ID (向 @userinfobot 发送消息获取你的数字 ID，支持多个，英文逗号分隔)
ALLOWED_USER_IDS=123456789,987654321

# 3. VPS API Token (在此填入您的 boil.network token 即可)
VPS_API_TOKEN=your_vps_token_here

# 查询与更换接口（默认已为您预配好 boil.network，无需修改）
VPS_QUERY_IP_URL=https://ippanel.boil.network/api/v1/getIP
VPS_QUERY_IP_METHOD=POST
VPS_CHANGE_IP_URL=https://ippanel.boil.network/api/v1/changeIP/
VPS_CHANGE_IP_METHOD=POST

# 4. 定时检测与体检设置
IPQUALITY_CRON_TIMES=09:00,21:00  # 定时体检时间点（每天早上9点与晚上21点）
TIMEZONE=Asia/Shanghai            # 调度时区（默认 Asia/Shanghai）
AUTO_TEST_ON_IP_CHANGE=true       # 换 IP 成功后是否自动进行质量体检
```

---

### 3. 运行机器人

```bash
# 测试启动
python main.py
```

在 Telegram 中向您的机器人发送 `/start` 即可开启主控面板！

---

## 🚀 生产环境守护部署

### 方式一：使用 Linux Systemd 守护进程 (强烈推荐)

在 VPS 宿主机上部署，能获得原生网络访问能力与最快响应速度：

1. 编辑服务文件中的路径：
   ```bash
   nano templates/homebroadband-bot.service
   ```
   修改 `WorkingDirectory` 和 `ExecStart` 为你实际部署的目录与 python 路径（如 `/root/JIABOT/venv/bin/python`）。

2. 复制并启用服务：
   ```bash
   sudo cp templates/homebroadband-bot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable homebroadband-bot
   sudo systemctl start homebroadband-bot
   ```

3. 查看运行状态与日志：
   ```bash
   sudo systemctl status homebroadband-bot
   sudo journalctl -u homebroadband-bot -f
   ```

---

### 方式二：使用 Docker & Docker Compose

若习惯容器化部署，项目已准备好 `Dockerfile` 与 `docker-compose.yml`（默认采用 `host` 网络模式）：

```bash
docker compose up -d --build
```

查看容器日志：
```bash
docker compose logs -f
```

---

## 📜 开源致谢

- 脚本体检引擎：[xykt/IPQuality (IP质量检测脚本)](https://github.com/xykt/IPQuality)
- Telegram Bot 框架：[python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
