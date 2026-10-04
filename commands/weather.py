"""天气查询命令：wttr.in 免费接口，无需 API Key，支持中文城市。"""
import time
import urllib.parse

import requests

from .base import command

_WTTR_URL = "https://wttr.in/{city}"
_TIMEOUT = 12
_RETRY = 3            # 最多请求次数（免费服务偶发断连，重试通常能成功）
_RETRY_GAP = 1.5      # 重试间隔（秒）


def _fetch_weather(city):
    """请求 wttr.in，返回 (文本, HTTP状态码)；网络异常向上抛。"""
    resp = requests.get(
        _WTTR_URL.format(city=urllib.parse.quote(city)),
        params={"format": "%l：%c %t，湿度%h，风%w", "lang": "zh"},
        headers={"User-Agent": "curl/8.0"},  # wttr.in 对默认 UA 返回 HTML
        timeout=_TIMEOUT,
    )
    return resp.text.strip(), resp.status_code


@command("天气", aliases=("weather", "tianqi", "查天气"), glue_args=True,
         help="#天气 城市 - 查实时天气，如 #天气 北京 或 #天气吉安")
def cmd_weather(ctx):
    city = (ctx.arg or "").strip()
    if not city:
        return "查哪儿的天气？用法：#天气 北京（连写也行：#天气吉安）"

    last_exc = None
    for attempt in range(1, _RETRY + 1):
        try:
            text, status = _fetch_weather(city)
            break
        except requests.RequestException as e:
            last_exc = e
            print(f" [命令] #天气 第{attempt}次请求失败: {e}")
            if attempt < _RETRY:
                time.sleep(_RETRY_GAP)
    else:
        return "天气服务连不上，稍后再试吧~"

    # wttr.in 查不到城市时可能返回 500 + "ERROR: Unknown location"
    if "Unknown location" in text or text.upper().startswith("ERROR") or status != 200 or not text:
        return f"没查到「{city}」的天气，换个城市名试试（直接用城市名，不带省份）？"
    return text
