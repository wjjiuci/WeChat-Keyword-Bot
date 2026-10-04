# WeChat-Keyword-Bot 微信群聊机器人

基于 [wxauto 3.9.2.1](https://github.com/cluic/wxauto)（UI 自动化）的 Windows 微信群聊机器人。
白名单监听、@ 识别、命令插件、关键词规则、AI 兜底回复、图片 OCR、AI 画图、SQLite 消息日志，全部本地运行。

## 功能特性

- **白名单机制**：只监听 `config.py` 里配置的群聊 / 好友，其他会话一律忽略
- **群聊触发机制**：不是每条都回——只有 @我 / 含触发词 / `#` 命令才回复，防刷屏（同群回复间隔可配）
- **@ 识别双信号**：文本规范化匹配（处理 U+2005 等特殊空白、短昵称边界防误判）+ UIA 子控件检测（微信原生 @ 元素），带昵称边界保护，不会把 `@小明哥` 误判成 `@小明`
- **命令插件框架**：`commands/` 目录即插即用，`#帮助` 菜单自动生成，新增命令只需 3 行代码
- **关键词规则**：口语化触发（如「在吗」「几点了」），支持 keyword / regex 两种模式
- **AI 兜底回复**：触发但未命中规则时，走 JEV 决策 + DeepSeek 生成拟人回复（需自行配置）
- **图片 OCR**：群图片自动下载 → RapidOCR 离线识别中文 → 以 `[图片] 识别文字` 参与后续流程，全程不阻塞
- **AI 画图**：`#画图` 命令，默认 Pollinations.ai 免费接口（零配置），可选智谱 CogView 升级
- **三队列 + 双线程架构**：主线程只做 wxauto UI 操作，OCR / AI / 画图都在后台线程，微信窗口不卡死
- **历史预热**：启动时忽略窗口里已有的历史消息，只响应启动后的新消息，避免重跑误报
- **SQLite 日志**：所有消息（含机器人自己的回复）落库，可追溯命中规则

## 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 |
| 微信客户端 | **3.9.12.1000**（不支持微信 4.x，4.x 请用 wxauto4） |
| Python | 3.10+（开发环境 3.12） |
| 其他 | 微信需保持登录且窗口可操作（UI 自动化原理，最小化可能影响识别） |

## 安装

```bash
pip install -r requirements.txt
```

## 配置

```bash
# 复制模板为本地配置（config.py 已被 .gitignore 排除，不会上传）
cp config.example.py config.py
```

编辑 `config.py`，逐项说明：

### 基础

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `WHITELIST` | 要监听的群名 / 好友昵称列表 | `["示例群名1"]` |
| `SELF_NICKNAME` | 机器人自己的微信昵称，用于识别 @我；多个昵称填列表 | `"我"` |
| `POLL_INTERVAL` | 轮询消息间隔（秒） | `2.0` |

### 群聊触发

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `TRIGGER_MODE` | `"at"`=仅@我 / `"keyword"`=仅触发词 / `"at_or_kw"`=二者皆可 | `"at_or_kw"` |
| `GROUP_TRIGGER_KEYWORDS` | 召唤词列表（@我自动识别，不用写在这里） | `["机器人", "小助手", "bot"]` |
| `GROUP_REPLY_INTERVAL` | 同群两次回复最小间隔（秒），防刷屏 | `5.0` |
| `REPLY_WITH_AT` | 群聊回复时是否 @ 对方 | `True` |
| `EMPTY_AT_REPLY` | 只 @ 我没说话时的回复，`""` 则沉默 | `"在的，说啥？"` |

### 回复规则

| 配置项 | 说明 |
|--------|------|
| `RULES` | 非命令式关键词规则，按顺序匹配命中第一条；`mode` 支持 `keyword`（子串）/`regex`（正则）；回复模板支持 `{time} {sender} {chat} {content} {joke}` 占位符 |
| `JOKES` | 笑话库，`#笑话` 和 `{joke}` 占位符使用 |
| `ENABLE_AI_REPLY` | 触发但未命中规则时是否调用 AI 兜底（`True`/`False`） |
| `OCR_ENABLED` | 是否开启图片 OCR 识别 |

### AI 画图

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `ZHIPU_API_KEY` | 智谱 API Key；**留空则用 Pollinations.ai 免费接口，零配置可用** | `""` |
| `IMAGE_GEN_MODEL` | 智谱模型（填了 Key 才生效） | `"cogview-3-flash"` |
| `IMAGE_GEN_SIZE` | 图片尺寸 `宽x高` | `"1024x1024"` |
| `IMAGE_GEN_TIMEOUT` | 生成/下载超时（秒） | `90` |

### AI 兜底回复（可选，进阶）

`ENABLE_AI_REPLY = True` 时，[ai_reply.py](ai_reply.py) 会从同级目录的
`../WeChat-Auto-Reply-System-main/config.py` 读取 JEV / DeepSeek 的 API Key、人设（PERSONA）、
关系（RELATIONSHIP）等配置。

- 没有这个项目？把 `ENABLE_AI_REPLY` 设为 `False`，机器人只走命令 + 关键词规则，其余功能不受影响
- 有这个项目？参考其 README 配置 [JEV](https://typesafe.ai) 与 DeepSeek 的 Key 即可

## 使用

```bash
python bot.py
```

启动后先看控制台横幅确认配置生效，再到群里测试：

| 群里发 | 效果 |
|--------|------|
| `@机器人 #帮助` | 弹出全部指令菜单（自动生成） |
| `#时间` / `@机器人 几点了` | 报当前时间 |
| `#天气 北京` / `#天气北京` / `@机器人 查天气 上海` | 实时天气 |
| `#笑话` / `#骰子` | 随机笑话 / 掷骰子 |
| `#抽签` / `#抽签 吃饭 吃面` | 今日签运 / 帮你拍板 |
| `#画图 一只在月球上打篮球的柴犬` | AI 画图，画好直接发群里 |
| `@机器人 今晚吃啥` | 未命中命令/规则 → AI 兜底回复 |
| 普通闲聊（未触发） | 只记进 SQLite，不回复 |

> 所有命令都支持：`#命令`、`@机器人 命令`、`@机器人 #命令` 三种写法；天气/画图还支持命令与参数连写。

## 扩展新命令

在 `commands/` 下任意插件文件里加一个函数，再到 `commands/__init__.py` import 该模块即可：

```python
from .base import command

@command("打脸", aliases=("pa",), help="#打脸 - 拍一下")
def cmd_slap(ctx):
    return f"啪！{ctx.sender} 被打了一巴掌"
```

`#帮助` 菜单自动收录。`ctx` 提供 `chat / sender / content / arg / is_group`，
另有 `deliver_text(text)`、`deliver_image(path, caption)` 异步投递回调（参考 [commands/draw.py](commands/draw.py)）。

## 数据与隐私

- 所有消息记录只存在本地 `messages.db`（WAL 模式），已在 [.gitignore](.gitignore) 排除
- `config.py` 含你的真实群名、昵称与 Key，已被 .gitignore 排除，不会上传
- 请勿将本机器人用于骚扰、广告或其他违反微信使用规范的行为

## 常见问题

- **提示"未找到微信窗口"**：确认微信版本是 3.9.12.1000 且已登录；4.x 不兼容本项目的 wxauto 版本
- **偶尔 COMError / UIA 报错**：微信窗口被遮挡或正在加载，程序会自动重试；频繁出现就保持微信前台、关闭全屏模式
- **群里发消息没反应**：检查是否满足触发条件（@我 / 触发词 / #命令）、是否在防刷屏间隔内、群名是否在 WHITELIST
- **启动后回复了旧消息**：3.0 版本起有历史预热，若仍出现请提 issue
- **画图说接口异常**：免费接口偶发排队/断连，稍后重试；对质量有要求可配置智谱 Key

## 免责声明

本项目仅供学习交流，基于 UI 自动化实现，存在被微信检测限制的可能，请自行评估风险。
使用本项目产生的任何后果由使用者自行承担。
