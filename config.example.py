# ============================================================
# 微信群聊机器人配置模板
# 使用方法：复制本文件为 config.py，然后填入你的真实配置
# ============================================================

# 白名单：只监听并响应这些群聊（填群名）
WHITELIST = [
    "示例群名1",
    "示例群名2",
]

# ---------- 群聊触发机制 ----------
# 群聊里不会每条消息都回，必须满足触发条件才回复
# trigger_mode:
#   "at"       = 只有 @我 时才回复
#   "keyword"  = 消息包含触发词时回复
#   "at_or_kw" = @我 或 含触发词 都回复（默认）
TRIGGER_MODE = "at_or_kw"
GROUP_TRIGGER_KEYWORDS = ["机器人", "小助手", "bot"]

# 群聊防刷屏：同一群两次回复的最小间隔（秒）
GROUP_REPLY_INTERVAL = 5.0

# 是否在群聊回复时 @ 对方
REPLY_WITH_AT = True

# 群里只 @ 我但没说话时的固定回复（留空 "" 则不回复）
EMPTY_AT_REPLY = "在的，说啥？"

# ---------- 非命令式关键词规则 ----------
# 按顺序匹配，命中第一条即回复
# 注意：# 开头的指令请在 commands/ 插件里写（自动出现在 #帮助 菜单），
#       这里只放不带 # 的口语化关键词
# mode: "keyword"=子串包含；"regex"=正则
# reply 支持占位符：{time} {sender} {chat} {content}
RULES = [
    {"match": "你是谁",     "reply": "我是群里的机器人小助手，有啥可以喊我~",            "mode": "keyword"},
    {"match": "你能做什么", "reply": "发 #帮助 看我会的指令，或者@我聊天也行~",          "mode": "keyword"},
    {"match": "在吗",       "reply": "在的在的，喊我干啥？",                             "mode": "keyword"},
    {"match": "几点",       "reply": "现在是 {time}",                                  "mode": "keyword"},
    {"match": "时间",       "reply": "现在是 {time}",                                  "mode": "keyword"},
]

# 笑话库（#笑话 随机返回）
JOKES = [
    "为什么程序员分不清万圣节和圣诞节？因为 Oct 31 == Dec 25。",
    "我跟我的床是真爱，但是闹钟非要拆散我们。",
]

# ---------- 运行参数 ----------
POLL_INTERVAL = 2.0
# 机器人自己的微信昵称（用于识别群内 @我）；有多个昵称/群昵称时可填列表，如 ["我", "小助手"]
SELF_NICKNAME = "我"

# ---------- AI 兜底回复 ----------
ENABLE_AI_REPLY = True

# ---------- 图片 OCR ----------
OCR_ENABLED = True

# ---------- 文生图 #画图 ----------
# 默认走 Pollinations.ai 免费接口，零配置直接可用
# 可选升级：填智谱 API Key（https://bigmodel.cn 申请，0.06元/次），中文理解更好、能在图里生成汉字
ZHIPU_API_KEY = ""
IMAGE_GEN_MODEL = "cogview-3-flash"
IMAGE_GEN_SIZE = "1024x1024"
IMAGE_GEN_TIMEOUT = 90
