"""文生图子模块：默认用 Pollinations.ai 免费接口（无需注册/Key），
可选配置智谱 CogView API Key 升级画质。

后端选择：
  - ZHIPU_API_KEY 已填 → 智谱 CogView（0.06 元/次，中文理解好、能在图里生成汉字）
  - 未填 → Pollinations.ai（免费，FLUX 模型，GET 即返回图片）

生成在后台线程执行（一条图约 5~30 秒），不阻塞回复线程和微信窗口；
生成的图片由调用方（bot.py 主线程）通过 wxauto SendFiles 发送后自动清理。
"""
import os
import time
import tempfile
import urllib.parse

import requests

try:
    from config import (
        ZHIPU_API_KEY,
        IMAGE_GEN_MODEL as _MODEL,
        IMAGE_GEN_SIZE as _SIZE,
        IMAGE_GEN_TIMEOUT as _TIMEOUT,
    )
except ImportError:
    ZHIPU_API_KEY = ""
    _MODEL, _SIZE, _TIMEOUT = "cogview-3-flash", "1024x1024", 90

_ZHIPU_URL = "https://open.bigmodel.cn/api/paas/v4/images/generations"
_POLLINATIONS_URL = "https://image.pollinations.ai/prompt/"
_IMG_DIR = os.path.join(tempfile.gettempdir(), "wxbot_draw")


def _save_image(content: bytes) -> str:
    """把图片字节写入临时目录，返回文件路径。"""
    os.makedirs(_IMG_DIR, exist_ok=True)
    path = os.path.join(_IMG_DIR, f"draw_{int(time.time() * 1000)}.png")
    with open(path, "wb") as f:
        f.write(content)
    return path


def _generate_pollinations(prompt) -> str:
    """Pollinations.ai 免费文生图：GET 即返回图片字节。"""
    size = _SIZE.split("x")
    url = _POLLINATIONS_URL + urllib.parse.quote(prompt)
    resp = requests.get(
        url,
        params={"width": size[0], "height": size[1], "nologo": "true"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "")
    if not ctype.startswith("image") or len(resp.content) < 1000:
        raise RuntimeError("免费画图接口返回异常，请稍后再试")
    return _save_image(resp.content)


def _generate_zhipu(prompt) -> str:
    """智谱 CogView 文生图，返回本地文件路径。"""
    resp = requests.post(
        _ZHIPU_URL,
        headers={"Authorization": f"Bearer {ZHIPU_API_KEY}"},
        json={"model": _MODEL, "prompt": prompt, "size": _SIZE},
        timeout=_TIMEOUT,
    )
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"接口返回非 JSON（HTTP {resp.status_code}）")
    if resp.status_code != 200 or "data" not in data:
        msg = data.get("error", {}).get("message") or data.get("message") or resp.text[:120]
        raise RuntimeError(f"接口异常(HTTP {resp.status_code}): {msg}")

    url = (data.get("data") or [{}])[0].get("url")
    if not url:
        raise RuntimeError("接口未返回图片地址（可能触发了内容安全拦截）")

    img_resp = requests.get(url, timeout=_TIMEOUT)
    img_resp.raise_for_status()
    return _save_image(img_resp.content)


def generate_image(prompt) -> str:
    """文生图入口：有智谱 Key 走 CogView，否则走免费接口。返回本地文件路径。"""
    if ZHIPU_API_KEY:
        return _generate_zhipu(prompt)
    return _generate_pollinations(prompt)
