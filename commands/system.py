"""系统类命令：报时、动态帮助菜单。"""
import time

from .base import command, COMMANDS


@command("时间", aliases=("几点", "now", "time"), help="#时间 - 报当前时间")
def cmd_time(ctx):
    return f"现在是 {time.strftime('%H:%M')}"


@command("帮助", aliases=("help", "功能", "菜单", "menu"), help="#帮助 - 显示所有可用指令")
def cmd_help(ctx):
    """帮助菜单从注册表动态生成；别名共用同一个 entry，需去重。"""
    lines = ["可用指令："]
    seen = set()
    for entry in COMMANDS.values():
        if id(entry) in seen:
            continue
        seen.add(id(entry))
        if entry.help_text:
            lines.append(entry.help_text)
    lines.append("也可以直接 @我 问问题~")
    return "\n".join(lines)
