"""关键词 / 正则匹配引擎。"""
import re
import random
from datetime import datetime

try:
    from config import JOKES
except ImportError:
    JOKES = []


def match_rule(text, rules):
    """按顺序匹配规则，命中第一条即返回 (rule, reply_template)；未命中返回 (None, None)。"""
    if not text:
        return None, None
    for rule in rules:
        mode = rule.get("mode", "keyword")
        pattern = rule.get("match", "")
        if not pattern:
            continue
        case_sensitive = rule.get("case_sensitive", False)

        if mode == "regex":
            flags = 0 if case_sensitive else re.IGNORECASE
            if re.search(pattern, text, flags):
                return rule, rule.get("reply", "")
        else:  # keyword（子串包含）
            if case_sensitive:
                hit = pattern in text
            else:
                hit = pattern.lower() in text.lower()
            if hit:
                return rule, rule.get("reply", "")
    return None, None


def render_reply(template, sender="", chat="", content=""):
    """把回复模板里的占位符替换成实际值。
    支持 {time} {sender} {chat} {content} {joke}。
    """
    if not template:
        return ""
    now = datetime.now().strftime("%H:%M")
    joke = random.choice(JOKES) if JOKES else "（笑话库为空）"
    try:
        return template.format(time=now, sender=sender, chat=chat, content=content, joke=joke)
    except (KeyError, IndexError):
        # 模板里有未定义的占位符时原样返回，避免崩溃
        return template
