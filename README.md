# Garmin Connect China MCP Server

佳明中国大陆版 (garmin.cn) 的 MCP 数据读取服务。

通过 MCP (Model Context Protocol) 协议，让 AI 助手可以直接读取你的佳明健康和运动数据。

## 功能

| 类别 | 工具 | 说明 |
|------|------|------|
| 🏃 运动 | `get_activities` | 运动列表 |
| | `get_activities_by_date` | 按日期查运动 |
| | `get_activity` | 运动详情 |
| | `get_activity_details` | 运动详细数据 |
| | `get_activity_splits` | 每公里配速 |
| | `get_activity_hr_zones` | 心率区间 |
| | `get_activity_types` | 运动类型列表 |
| | `get_last_activity` | 最近一次运动 |
| 📊 训练 | `get_training_status` | 训练状态/VO2 Max |
| | `get_training_readiness` | 训练准备度 |
| 👤 资料 | `get_profile` | 用户信息 |
| | `get_devices` | 设备列表 |
| | `get_primary_device` | 主训练设备 |
| 💤 睡眠 | `get_sleep` | 睡眠数据/得分/阶段 |
| ❤️ HRV | `get_hrv` | 心率变异性 |
| 😰 压力 | `get_stress` | 全天压力数据 |
| 🩸 血氧 | `get_spo2` | SpO2 数据 |
| 🫁 呼吸 | `get_respiration` | 呼吸频率 |
| 🏅 其他 | `get_earned_badges` | 已获徽章 |
| | `get_gear` | 装备数据 |

## 为什么需要这个？

佳明中国版 (`garmin.cn`) 的 API 架构和国际版 (`garmin.com`) 完全不同：

- 国际版的 `garminconnect` Python 库**不支持**中国版
- 中国版使用 `/gc-api/` 服务端代理，而不是直接调 `connectapi.garmin.cn`
- 登录使用 `sso.garmin.cn/mobile/api/login`（移动端 API）
- 需要 `curl_cffi` 进行 Chrome TLS 指纹伪装来绕过 Cloudflare

## 安装

```bash
# 克隆仓库
git clone https://github.com/<your-username>/garmin-cn-mcp.git
cd garmin-cn-mcp

# 安装依赖
pip install -r requirements.txt
```

## 配置

在你的 MCP 客户端配置中添加：

```json
{
  "mcpServers": {
    "garmin-cn": {
      "command": "python3",
      "args": ["/path/to/garmin_cn_mcp.py"],
      "env": {
        "GARMIN_CN_EMAIL": "your-garmin-email@example.com",
        "GARMIN_CN_PASSWORD": "your-password"
      }
    }
  }
}
```

### Hermes Agent 配置

```bash
hermes mcp add garmin-cn -- python3 /path/to/garmin_cn_mcp.py
```

然后在 `~/.hermes/.env` 中添加：
```
GARMIN_CN_EMAIL=your-garmin-email@example.com
GARMIN_CN_PASSWORD=your-password
```

## 使用示例

配置好后，AI 助手可以直接查询你的佳明数据：

- "我昨天睡得怎么样？"
- "最近一周的运动记录"
- "今天的 HRV 和压力数据"
- "我的训练状态和 VO2 Max"

## 技术细节

### API 路径

| 数据类型 | API 路径 |
|---------|---------|
| 运动列表 | `/gc-api/activitylist-service/activities/search/activities` |
| 运动详情 | `/gc-api/activity-service/activity/{id}` |
| 睡眠数据 | `/gc-api/wellness-service/wellness/dailySleepData?date=` |
| HRV | `/gc-api/hrv-service/hrv/{date}` |
| 压力 | `/gc-api/wellness-service/wellness/dailyStress/{date}` |
| 血氧 | `/gc-api/wellness-service/wellness/daily/spo2/{date}` |
| 呼吸 | `/gc-api/wellness-service/wellness/daily/respiration/{date}` |

### 登录流程

1. POST `sso.garmin.cn/mobile/api/login` → 获取 service ticket
2. GET `connect.garmin.cn/modern?ticket=...` → 获取 JWT_WEB cookie + CSRF token
3. 后续 API 调用通过 `/gc-api/` 代理，携带 CSRF token

## 依赖

- Python 3.10+
- mcp (MCP SDK)
- curl_cffi (Chrome TLS 指纹)

## 许可证

MIT License
