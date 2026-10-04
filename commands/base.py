"""命令插件框架。

设计（参考 NGCBot / XYBotV2 的插件注册思路，做轻量版）：
  - 每个 #命令 用 @command 装饰器注册到全局 COMMANDS
  - 支持命令别名（如 #天气 / #weather）
  - #帮助 菜单从注册表动态生成，新增命令无需改 bot.py
  - dispatch() 统一负责命令解析、路由、异常兜底

新增一个命令只需两步：
  1. 在 commands/ 下新建（或在现有插件文件里加）一个函数
  2. 用 @command("命令名", aliases=("别名",), help="#命令 参数 - 说明") 装饰
  3. 在 commands/__init__.py 里 import 一下模块
"""
from dataclasses import dataclass

# 命令名(小写) -> CommandEntry，别名同样指向同一个 entry
COMMANDS = {}

# 允许“命令+参数连写”的命令名集合（如 #天气吉安），值为 entry，长名优先
_GLUE_ENTRIES = {}

# 未知 #命令 的统一提示
UNKNOWN_TIP = "没这个指令，发 #帮助 看看我都会啥~"


@dataclass
class Context:
    """命令执行上下文。"""
    chat: str            # 群名 / 私聊对象名
    sender: str          # 发送者昵称
    content: str         # 清洗 @ 前缀后的完整文本
    arg: str             # 命令名之后的参数原文（如 '#天气 北京' -> '北京'）
    is_group: bool       # 是否群聊
    # 异步投递回调（bot.py 注入；默认 None 便于单测直接构造 Context）
    deliver_text: object = None    # callable(text)          -> 追加发一条文本
    deliver_image: object = None   # callable(path, caption) -> 发本地图片


@dataclass
class CommandEntry:
    name: str            # 主命令名
    aliases: tuple       # 别名
    help_text: str       # 帮助菜单里展示的一行说明
    func: object         # 处理函数 ctx -> Optional[str]
    glue_args: bool = False  # 允许命令与参数连写（如 #天气吉安）

    def handle(self, ctx):
        return self.func(ctx)


class command:
    """命令注册装饰器。

    用法::

        @command("天气", aliases=("weather",), glue_args=True,
                 help="#天气 城市 - 查询天气（#天气吉安 也行）")
        def cmd_weather(ctx):
            return "晴"
    """

    def __init__(self, name, aliases=(), help="", glue_args=False):
        self.name = name
        self.aliases = tuple(aliases)
        self.help_text = help
        self.glue_args = glue_args

    def __call__(self, func):
        entry = CommandEntry(self.name, self.aliases, self.help_text, func,
                             glue_args=self.glue_args)
        COMMANDS[self.name.lower()] = entry
        for alias in self.aliases:
            COMMANDS[alias.lower()] = entry
        if self.glue_args:
            _GLUE_ENTRIES[self.name.lower()] = entry
            for alias in self.aliases:
                _GLUE_ENTRIES[alias.lower()] = entry
        return func


def resolve_command(body):
    """解析去掉前导 # 后的文本（如 '天气 北京' / '天气江西吉安'）。

    返回 (entry, arg)；解析不到返回 (None, "")。
    解析顺序：
      1. 精确匹配命令名/别名（按空白分词）
      2. 仅对 glue_args 命令做前缀回退，支持 '#天气吉安' 这种连写
    """
    body = (body or "").strip()
    if not body:
        return None, ""

    parts = body.split(maxsplit=1)
    key = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    entry = COMMANDS.get(key)
    if entry is not None:
        return entry, arg

    # 连写回退：长命令名优先，避免短名误吃（如同时有 '天' 和 '天气'）
    for glue_key in sorted(_GLUE_ENTRIES, key=len, reverse=True):
        if key.startswith(glue_key) and len(key) > len(glue_key):
            glued_arg = key[len(glue_key):] + ((" " + arg) if arg else "")
            return _GLUE_ENTRIES[glue_key], glued_arg.strip()

    return None, ""


def dispatch(text, ctx):
    """把文本路由到已注册命令。

    返回 (handled, reply)：
      - 非 # 开头：(False, None)，交给关键词规则 / AI
      - 已注册命令：(True, 回复文本)，命令返回 None/空串时为 (True, "")
      - 未知命令：(True, UNKNOWN_TIP)
    """
    body = (text or "").strip()
    if not body.startswith("#"):
        return False, None

    entry, arg = resolve_command(body[1:])
    ctx.arg = arg
    if entry is None:
        return True, UNKNOWN_TIP

    try:
        reply = entry.handle(ctx)
        return True, (reply or "")
    except Exception as e:
        print(f" [命令] #{entry.name} 执行异常: {e}")
        return True, "这条指令我处理的时候出了点问题，等下再试~"
