"""娱乐类命令：笑话、骰子、抽签。"""
import re
import random

from .base import command

try:
    from config import JOKES
except ImportError:
    JOKES = []

# 传统签运（加权随机，中间签概率高，大凶大吉概率低）
_FORTUNES = [
    ("大吉", 4), ("中吉", 9), ("小吉", 15), ("吉", 22),
    ("末吉", 15), ("凶", 9), ("大凶", 4),
]
_FORTUNE_HINT = {
    "大吉": "想干啥就干啥，今天运气站你这边！",
    "中吉": "顺顺当当，适合搞点事情。",
    "小吉": "有点小好运，别嫌少。",
    "吉": "平平安安就是福。",
    "末吉": "一般般，躺着最安全。",
    "凶": "今天少说话多吃饭，过了就好。",
    "大凶": "建议回去再睡一觉重启今天。",
}


@command("笑话", aliases=("joke", "讲个笑话"), help="#笑话 - 随机讲个笑话")
def cmd_joke(ctx):
    if not JOKES:
        return "笑话库空了，让主人给我补几条吧~"
    return random.choice(JOKES)


@command("骰子", aliases=("dice", "色子", "摇骰子"), help="#骰子 - 掷一颗骰子")
def cmd_dice(ctx):
    return f"骰子掷出：{random.randint(1, 6)} 点"


@command("抽签", aliases=("choose", "选一个", "选择困难"),
         help="#抽签 [选项1 选项2 ...] - 给了选项帮你拍板，没给就测今日签运")
def cmd_draw(ctx):
    arg = (ctx.arg or "").strip()
    if arg:
        # 支持空格 / 逗号分隔选项
        options = [o for o in re.split(r"[,，、\s]+", arg) if o]
        if len(options) < 2:
            return "至少给俩选项我才好帮你选，比如：#抽签 吃饭 吃面"
        pick = random.choice(options)
        return f"我帮你定了：{pick}！别纠结了，冲！"

    labels = [name for name, _ in _FORTUNES]
    weights = [w for _, w in _FORTUNES]
    fortune = random.choices(labels, weights=weights, k=1)[0]
    return f"今日签运：{fortune}。{_FORTUNE_HINT[fortune]}"
