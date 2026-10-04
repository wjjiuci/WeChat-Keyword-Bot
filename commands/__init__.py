"""命令插件包。

import 本包即自动注册所有命令；#帮助 菜单按下面的 import 顺序排列。
新增插件文件后，在这里加一行 import 即可被机器人识别。
"""
from .base import command, Context, CommandEntry, COMMANDS, dispatch, resolve_command

# 导入即注册，顺序即 #帮助 菜单里的展示顺序
from . import system    # noqa: F401  时间、帮助
from . import fun       # noqa: F401  笑话、骰子、抽签
from . import weather   # noqa: F401  天气
from . import draw      # noqa: F401  画图（文生图）

__all__ = ["command", "Context", "CommandEntry", "COMMANDS", "dispatch", "resolve_command"]
