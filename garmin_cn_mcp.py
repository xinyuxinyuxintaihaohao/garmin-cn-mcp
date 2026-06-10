#!/usr/bin/env python3
"""
Garmin Connect China MCP Server
通过 MCP 协议读取佳明中国大陆版 (garmin.cn) 的健康和运动数据

使用 connect.garmin.cn 的 /gc-api/ 服务器端代理访问 API。
"""

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# ─── 初始化 MCP 服务器 ───────────────────────────────────────────
mcp = FastMCP(
    "garmin-cn",
    instructions="佳明中国大陆版数据读取服务。连接 connect.garmin.cn，获取运动、健康、睡眠、心率等数据。",
)

# ─── 会话管理 ─────────────────────────────────────────────────────
_session = None
_csrf_token = None
_token_dir = Path.home() / ".hermes" / "garmin_tokens"
_token_file = _token_dir / "garmin_cn_session.json"


def _get_session():
    """获取已认证的 HTTP 会话"""
    global _session, _csrf_token

    if _session is not None:
        return _session, _csrf_token

    import curl_cffi.requests as cffi_requests

    _token_dir.mkdir(parents=True, exist_ok=True)

    # 尝试从缓存恢复会话
    if _token_file.exists():
        try:
            cached = json.loads(_token_file.read_text())
            if cached.get("expires", 0) > time.time():
                sess = cffi_requests.Session(impersonate="chrome", timeout=30)
                for name, value in cached.get("cookies", {}).items():
                    sess.cookies.set(name, value, domain=cached.get("domain", ".connect.garmin.cn"))
                _session = sess
                _csrf_token = cached.get("csrf")
                return _session, _csrf_token
        except Exception:
            pass

    # 新登录
    email = os.environ.get("GARMIN_CN_EMAIL") or os.environ.get("GARMIN_EMAIL")
    password = os.environ.get("GARMIN_CN_PASSWORD") or os.environ.get("GARMIN_PASSWORD")

    if not email or not password:
        raise RuntimeError(
            "需要设置佳明账号凭据。请在 ~/.hermes/.env 中添加:\n"
            "  GARMIN_CN_EMAIL=你的佳明邮箱\n"
            "  GARMIN_CN_PASSWORD=密码\n"
            "然后重启 MCP 服务器。"
        )

    sess = cffi_requests.Session(impersonate="chrome", timeout=30)

    # Step 1: 移动端 API 登录获取 ticket
    r = sess.post(
        "https://sso.garmin.cn/mobile/api/login",
        params={"clientId": "GCM_ANDROID_DARK", "service": "https://connect.garmin.cn/modern"},
        json={"username": email, "password": password, "rememberMe": True, "captchaToken": ""},
        timeout=30,
    )
    data = r.json()
    if data.get("responseStatus", {}).get("type") != "SUCCESSFUL":
        raise RuntimeError(f"佳明登录失败: {data.get('responseStatus', {}).get('message', '未知错误')}")

    ticket = data["serviceTicketId"]

    # Step 2: 消费 ticket 获取 JWT_WEB + session cookie
    r = sess.get("https://connect.garmin.cn/modern", params={"ticket": ticket}, allow_redirects=True, timeout=30)

    # Step 3: 提取 CSRF token
    csrf_match = re.search(r'<meta[^>]*name=["\']csrf-token["\'][^>]*content=["\']([^"\']+)', r.text)
    csrf = csrf_match.group(1) if csrf_match else ""

    # 缓存会话 (有效期 4 小时)
    cookies_to_save = {}
    for c in sess.cookies.jar:
        if "connect.garmin.cn" in c.domain:
            cookies_to_save[c.name] = c.value

    _token_file.write_text(json.dumps({
        "cookies": cookies_to_save,
        "csrf": csrf,
        "domain": ".connect.garmin.cn",
        "expires": time.time() + 4 * 3600,
    }))

    _session = sess
    _csrf_token = csrf
    return _session, _csrf_token


def _api_get(path: str, backend: str = "gc-api") -> Any:
    """通过 /gc-api/ 代理调用 API"""
    sess, csrf = _get_session()
    headers = {
        "Accept": "application/json",
        "connect-csrf-token": csrf,
    }
    url = f"https://connect.garmin.cn/{backend}{path}"
    r = sess.get(url, headers=headers, timeout=30)

    if r.status_code == 401:
        # 会话过期，清除缓存重试
        global _session, _csrf_token
        _session = None
        _csrf_token = None
        if _token_file.exists():
            _token_file.unlink()
        sess, csrf = _get_session()
        headers["connect-csrf-token"] = csrf
        r = sess.get(url, headers=headers, timeout=30)

    if r.status_code == 204:
        return {}
    if r.ok:
        return r.json()
    raise RuntimeError(f"API 错误 {r.status_code}: {path} - {r.text[:200]}")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def _jd(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# ═══════════════════════════════════════════════════════════════════
# Tools
# ═══════════════════════════════════════════════════════════════════


@mcp.tool()
def get_profile() -> str:
    """获取佳明用户资料（姓名、单位制等）"""
    profile = _api_get("/userprofile-service/socialProfile")
    settings = _api_get("/userprofile-service/userprofile/user-settings")
    return _jd({
        "profile": profile,
        "settings": {
            "measurementSystem": settings.get("userData", {}).get("measurementSystem"),
            "timeZone": settings.get("userData", {}).get("timeZone"),
        },
    })


@mcp.tool()
def get_devices() -> str:
    """获取已绑定的佳明设备列表"""
    return _jd(_api_get("/device-service/deviceregistration/devices"))


@mcp.tool()
def get_primary_device() -> str:
    """获取主训练设备信息"""
    return _jd(_api_get("/web-gateway/device-info/primary-training-device"))


@mcp.tool()
def get_activities(start: int = 0, limit: int = 20) -> str:
    """获取最近的运动记录列表

    Args:
        start: 起始索引（从0开始），默认0
        limit: 返回数量，默认20，最大50
    """
    limit = min(limit, 50)
    return _jd(_api_get(f"/activitylist-service/activities/search/activities?start={start}&limit={limit}"))


@mcp.tool()
def get_activities_by_date(start: str = "", end: str = "", activity_type: str = "") -> str:
    """按日期范围获取运动记录

    Args:
        start: 开始日期 YYYY-MM-DD，默认7天前
        end: 结束日期 YYYY-MM-DD，默认今天
        activity_type: 运动类型过滤，如 running, cycling, strength_training 等（可选）
    """
    start = start or _days_ago(7)
    end = end or _today()
    params = f"?startDate={start}&endDate={end}"
    if activity_type:
        params += f"&activityType={activity_type}"
    return _jd(_api_get(f"/activitylist-service/activities/search/activities{params}&start=0&limit=100"))


@mcp.tool()
def get_activity(activity_id: str) -> str:
    """获取单个运动的详细数据

    Args:
        activity_id: 运动ID（从 get_activities 获取）
    """
    return _jd(_api_get(f"/activity-service/activity/{activity_id}"))


@mcp.tool()
def get_activity_details(activity_id: str) -> str:
    """获取运动的详细数据（含分段、心率区间等）

    Args:
        activity_id: 运动ID
    """
    return _jd(_api_get(f"/activity-service/activity/{activity_id}/details"))


@mcp.tool()
def get_activity_splits(activity_id: str) -> str:
    """获取运动的分段数据（每公里配速等）

    Args:
        activity_id: 运动ID
    """
    return _jd(_api_get(f"/activity-service/activity/{activity_id}/splits"))


@mcp.tool()
def get_activity_hr_zones(activity_id: str) -> str:
    """获取运动的心率区间分布

    Args:
        activity_id: 运动ID
    """
    return _jd(_api_get(f"/activity-service/activity/{activity_id}/hrTimeInZones"))


@mcp.tool()
def get_activity_types() -> str:
    """获取支持的运动类型列表"""
    return _jd(_api_get("/activity-service/activity/activityTypes"))


@mcp.tool()
def get_last_activity() -> str:
    """获取最近一次运动"""
    activities = _api_get("/activitylist-service/activities/search/activities?start=0&limit=1")
    if isinstance(activities, list) and len(activities) > 0:
        return _jd(activities[0])
    return _jd({"message": "没有找到运动记录"})


@mcp.tool()
def get_training_status(date: str = "") -> str:
    """获取训练状态（训练负荷、恢复时间、VO2 Max 等）

    Args:
        date: 日期 YYYY-MM-DD，默认今天
    """
    date = date or _today()
    return _jd(_api_get(f"/metrics-service/metrics/trainingstatus/aggregated/{date}"))


@mcp.tool()
def get_training_readiness(date: str = "") -> str:
    """获取训练准备度

    Args:
        date: 日期 YYYY-MM-DD，默认今天
    """
    date = date or _today()
    return _jd(_api_get(f"/metrics-service/metrics/trainingreadiness/{date}"))


@mcp.tool()
def get_earned_badges() -> str:
    """获取已获得的徽章"""
    return _jd(_api_get("/badge-service/badge/earned"))


@mcp.tool()
def get_gear() -> str:
    """获取装备数据（跑鞋、自行车等）"""
    return _jd(_api_get("/gear-service/gear/filterGear", backend="gc-api"))


# ─── 新增：睡眠 / 压力 / HRV / 血氧 / 呼吸 ──────────────────────


@mcp.tool()
def get_sleep(date: str = "") -> str:
    """获取某天的睡眠数据（深睡/浅睡/REM/醒来时长、睡眠得分、睡眠压力、心率、血氧等）

    Args:
        date: 日期 YYYY-MM-DD，默认昨天（因为当天睡眠数据可能还未同步）
    """
    date = date or _days_ago(1)
    return _jd(_api_get(f"/wellness-service/wellness/dailySleepData?date={date}"))


@mcp.tool()
def get_hrv(date: str = "") -> str:
    """获取某天的 HRV（心率变异性）数据

    Args:
        date: 日期 YYYY-MM-DD，默认昨天
    """
    date = date or _days_ago(1)
    return _jd(_api_get(f"/hrv-service/hrv/{date}"))


@mcp.tool()
def get_stress(date: str = "") -> str:
    """获取某天的压力数据（全天压力均值、峰值等）

    Args:
        date: 日期 YYYY-MM-DD，默认今天
    """
    date = date or _today()
    return _jd(_api_get(f"/wellness-service/wellness/dailyStress/{date}"))


@mcp.tool()
def get_spo2(date: str = "") -> str:
    """获取某天的血氧数据（SpO2 均值、最低值）

    Args:
        date: 日期 YYYY-MM-DD，默认今天
    """
    date = date or _today()
    return _jd(_api_get(f"/wellness-service/wellness/daily/spo2/{date}"))


@mcp.tool()
def get_respiration(date: str = "") -> str:
    """获取某天的呼吸数据（呼吸频率均值、最小、最大）

    Args:
        date: 日期 YYYY-MM-DD，默认今天
    """
    date = date or _today()
    return _jd(_api_get(f"/wellness-service/wellness/daily/respiration/{date}"))


# ═══════════════════════════════════════════════════════════════════
# 启动
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run(transport="stdio")
