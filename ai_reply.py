"""AI 回复模块：复用 WeChat-Auto-Reply-System 的 JEV 决策 + DeepSeek 生成 + BERT 情感兜底。

本模块不从原项目 import（避免加载整个 WeChat_reply.py 及其副作用），
而是把核心逻辑搬过来；配置（API Key、人设、关系、模型路径）从原项目的 config.py 读取。
原项目代码保持不动。
"""
import os
import sys
import random
import requests
import importlib.util

# ---------- 读取原项目配置（用 importlib 直接加载，避免污染全局 config 命名空间） ----------
_AUTO_REPLY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "WeChat-Auto-Reply-System-main")
)
_ar_config_path = os.path.join(_AUTO_REPLY_DIR, "config.py")
_spec = importlib.util.spec_from_file_location("ar_config", _ar_config_path)
_ar_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ar_config)

PERSONA = _ar_config.PERSONA
RELATIONSHIP = _ar_config.RELATIONSHIP
RELATIONSHIP_CONTEXT = _ar_config.RELATIONSHIP_CONTEXT
JEV_API_KEY = _ar_config.JEV_API_KEY
DEEPSEEK_API_KEY = _ar_config.DEEPSEEK_API_KEY
AR_SELF_NICKNAME = _ar_config.SELF_NICKNAME
AR_TARGET_CONTACT = _ar_config.TARGET_CONTACT
MODEL_DIR_NAME = _ar_config.MODEL_DIR_NAME

# ---------- 全局常量（与原项目一致） ----------
RELATIONSHIP_KNOWLEDGE = {
    "恋人": (
        "对方是你的恋人。要点：先接住情绪再解决问题；多用昵称和亲昵语气；"
        "对方低落时先共情陪伴，别急着讲道理；可以有适当的占有欲和小撒娇。"
    ),
    "暧昧对象": (
        "你们在暧昧期。要点：保持一点神秘感和推拉，别太主动也别太冷；"
        "多制造轻松有趣的话题和下次见面的由头；对方分享生活时表现出兴趣，追问细节。"
    ),
    "朋友": (
        "对方是你的朋友。要点：轻松随意，互相调侃；对方吐槽时先认同再给建议；"
        "不用太客套，但对方认真说事时也要给靠谱回应。"
    ),
    "损友": (
        "对方是你的损友。要点：日常互损互怼，嘴贱但不真伤人；"
        "对方情绪低落时收起玩笑认真陪伴；平时可以使劲坑，但对方有事第一个上。"
    ),
    "长辈": (
        "对方是你的长辈。要点：尊重但不卑微；多听少说；不懂的事虚心请教；"
        "说话得体，避免过于随意的网络用语。"
    ),
    "家人": (
        "对方是你的家人。要点：亲近自然，可以撒娇也可以顶嘴但有分寸；"
        "关心要落到具体的事上（吃饭没、冷不冷），别光说空话。"
    ),
    "同事": (
        "对方是同事。要点：友好但保持职业边界；工作的事给明确答复；"
        "闲聊轻松但避开敏感话题和过度吐槽公司。"
    ),
    "客户": (
        "对方是客户。要点：专业、及时、可靠；先确认对方需求再答复；"
        "不轻易承诺做不到的事，价格问题不主动让步。"
    ),
}

EMOTION_GUIDE = {
    0: "对方这句话情绪偏负向。先接住他的情绪（认同、陪伴或站他这边），再回应事情本身，别讲大道理。",
    1: "对方这句话情绪中性。自然随意地接话即可，可以适当抖个机灵。",
    2: "对方这句话情绪正向。顺着他的开心聊，回应可以更热情、多捧场。",
}

JEV_MODEL = "typesafe/jev-1.13"
JEV_MIN_REPLY_PROB = 0.6
JEV_TIMEOUT = 15

JEV_EMOTION_TO_SENTIMENT = {
    "开心": 2, "兴奋": 2, "平静": 1, "调侃": 1,
    "阴阳怪气": 0, "生气": 0, "难过": 0, "疲惫": 0,
}

MAX_HISTORY = 6

PROGRESS_LABELS = {
    "sharing": "闲聊分享", "clarify": "等具体信息", "reassure": "等关心回应",
    "explain": "等澄清", "act": "等行动落实", "accepted": "已敲定等执行", "closing": "收尾告别",
}

ADVICE_MAP = {
    "answer_first": "直接回答对方问的事，给出具体信息（时间/地点/名字/选择），哪怕一句话也要答到位，结尾可以自然带个小问题",
    "catch_emotion": "先接住情绪再谈事：认同TA的感受、站TA这边，别讲道理、别急着给解决方案，等情绪落地再说事",
    "confirm_plan": "给明确答复：时间、地点、选哪个直接拍板，别用'都行''随便'糊弄",
    "show_care": "先表达在意：心疼一下或追问细节，让对方感到被重视，再自然延展",
    "play_along": "顺着梗接住并适度反击，可以损回去，保持轻松别当真",
    "return_topic": "简短回应当前话题后，主动抛一个和上下文相关的具体新话题（具体到事，别问'在干嘛'）",
    "none": "简短自然回应即可，不刻意延展",
}

EVENT_CARDS = [
    {"id": "invite_probe", "scene": "邀约安排", "question": "是在试探一起活动的意愿吗？",
     "signal": "在试探能否一起去", "ordinary": "只是分享活动信息"},
    {"id": "invite_plan", "scene": "邀约安排", "question": "现在是否在等时间地点？",
     "signal": "已有一起去的意向，等具体安排", "ordinary": "还没确认愿不愿意去"},
    {"id": "daily_vent", "scene": "日常分享", "question": "这会儿更需要倾听还是办法？",
     "signal": "想先吐槽、被理解", "ordinary": "明确在问解决办法"},
    {"id": "daily_share", "scene": "日常分享", "question": "这次分享更想得到什么？",
     "signal": "想让你参与这段经历", "ordinary": "只是告知一件事"},
    {"id": "care_checkin", "scene": "关心靠近", "question": "是在认真关心你的状态吗？",
     "signal": "根据具体近况主动关心", "ordinary": "普通寒暄或顺口问候"},
    {"id": "care_reassure", "scene": "关心靠近", "question": "是在确认自己有没有被重视吗？",
     "signal": "对被忽略表达担心，期待确认", "ordinary": "仅询问一个事实"},
    {"id": "tease_play", "scene": "玩笑试探", "question": "这句调侃是在轻松互动吗？",
     "signal": "双方语境支持友好的玩笑", "ordinary": "包含认真不满或不舒服"},
    {"id": "tease_probe", "scene": "玩笑试探", "question": "是在借玩笑试探你的态度吗？",
     "signal": "围绕明确话题试探你的态度", "ordinary": "单纯逗趣，没有足够试探线索"},
    {"id": "promise_followup", "scene": "约定记忆", "question": "是在追问之前约定的进展吗？",
     "signal": "希望知道约定是否落实", "ordinary": "只是回忆过去的事情"},
    {"id": "friction_hear", "scene": "委屈不满", "question": "这句不满更需要先被理解吗？",
     "signal": "在表达受伤或被忽略的感受", "ordinary": "主要在指出具体事实问题"},
]


# ---------- BERT 情感模型（懒加载） ----------
_sentiment_tokenizer = None
_sentiment_model = None


def load_sentiment_model():
    """懒加载本地 BERT 情感模型；模型不存在或加载失败返回 (None, None)。"""
    global _sentiment_tokenizer, _sentiment_model
    if _sentiment_tokenizer is not None and _sentiment_model is not None:
        return _sentiment_tokenizer, _sentiment_model
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    model_path = os.path.join(_AUTO_REPLY_DIR, MODEL_DIR_NAME)
    if not os.path.exists(model_path):
        print(f" [AI] 情感模型不存在: {model_path}，将仅使用 JEV 决策")
        return None, None
    try:
        print(f" [AI] 加载情感模型: {model_path}")
        _sentiment_tokenizer = AutoTokenizer.from_pretrained(model_path)
        _sentiment_model = AutoModelForSequenceClassification.from_pretrained(model_path)
        _sentiment_model.eval()
        return _sentiment_tokenizer, _sentiment_model
    except Exception as e:
        print(f" [AI] 情感模型加载失败: {e}")
        return None, None


def predict_sentiment(message: str) -> int:
    """情感分析：0=负向, 1=中性, 2=正向。模型不可用时返回 1（中性）。"""
    import torch
    tokenizer, model = load_sentiment_model()
    if tokenizer is None or model is None:
        return 1
    inputs = tokenizer(
        message, truncation=True, padding='max_length',
        max_length=128, return_tensors='pt'
    )
    with torch.no_grad():
        logits = model(**inputs).logits
        _, pred = torch.max(logits, dim=1)
    return pred.item()


# ---------- JEV 决策 ----------
def jev_decide(text: str, history: list = None):
    """调用 JEV 决策模型，一次请求并行判断情绪、意图、是否适合回复、对话阶段、动作。
    返回结构化 dict；未配置 Key 或调用失败返回 None。"""
    if not JEV_API_KEY:
        return None
    state = {"对方最新消息": text, "我与对方的关系": RELATIONSHIP}
    if history:
        state["最近对话"] = [f"{m['sender']}: {m['text']}" for m in history[-MAX_HISTORY:]]
    questions = {
        "emotion": {
            "type": "choice",
            "instructions": "这条消息发送者当前的情绪最接近哪一类？",
            "criteria": {
                "开心": "明显高兴、兴奋、分享好消息",
                "平静": "日常陈述，没有明显情绪波动",
                "调侃": "开玩笑、互损、抛梗，不带恶意",
                "阴阳怪气": "表面客气实际带刺、反讽",
                "生气": "愤怒、指责、不耐烦",
                "难过": "低落、委屈、受挫、累",
            },
        },
        "intent": {
            "type": "choice",
            "instructions": "发送者这条消息的意图最接近哪一类？",
            "criteria": {
                "提问": "在问问题、征求意见",
                "分享": "分享日常、心情、看到的东西",
                "吐槽": "抱怨发泄，想被认同而不是要解决方案",
                "邀约": "约着一起做事、打游戏、见面",
                "互损": "聊天互怼玩闹",
                "求助": "请求帮忙或建议",
            },
        },
        "should_reply": {
            "type": "noul",
            "instructions": "这是一个全自动微信回复助手。现在自动回复这条消息是否合适？",
            "criteria": {
                "true": "消息在抛话题、打招呼、问问题或期待回应，此时接话自然不突兀",
                "false": "消息明显在和群里别人说话、双方正在激烈争吵、或明确表示不想聊，自动回复会突兀或激化矛盾",
            },
        },
        "progress": {
            "type": "choice",
            "instructions": "当前这一步的对话在等待怎样的回应？只依据前文判断。",
            "criteria": {
                "sharing": "对方在分享经历或自然闲聊",
                "clarify": "对方在等具体事实或细节（时间、地点、名字、答案）",
                "reassure": "对方在等关心、重视或安抚的回应",
                "explain": "需要澄清误会或承认问题",
                "act": "已经解释过了，等具体行动落实",
                "accepted": "已明确接受安排，等执行或收尾",
                "closing": "明确告别或话题自然收尾",
            },
        },
        "action": {
            "type": "choice",
            "instructions": "结合上下文，我这一条回复最适合采取哪种动作？优先回应当前未回应的信息。",
            "criteria": {
                "answer_first": "对方在问问题或等确认：直接回答/拍板，给出具体信息，别绕弯",
                "catch_emotion": "对方在倾诉、抱怨或发泄：先接住情绪（认同、站TA这边），再回应内容，别讲道理",
                "confirm_plan": "对话正在敲定安排：给明确的时间/地点/选择，别含糊",
                "show_care": "对方在等关心：先表达在意，追问细节，让对方感到被重视",
                "play_along": "对方在开玩笑、互损、抛梗：顺着接梗适度反击，语气轻松",
                "return_topic": "话题快聊完了：简短回应后主动抛一个相关的新话题把球打回去",
                "none": "普通日常往来：简短自然回应即可，不用刻意延展",
            },
        },
    }
    for card in EVENT_CARDS:
        questions[f"reading_{card['id']}"] = {
            "type": "choice",
            "instructions": (
                f"只在此问题适合当前语境时判断，否则选 unclear。{card['question']}"
                "signal 和 ordinary 是平等的备选解释，不因为某个更戏剧化就选择它。"
            ),
            "criteria": {
                "signal": card["signal"],
                "ordinary": card["ordinary"],
                "unclear": "信息不足或此问题不适用，不能确定",
            },
        }
    try:
        r = requests.post(
            "https://api.typesafe.ai/v1/systemone",
            headers={"Authorization": f"Bearer {JEV_API_KEY}", "Content-Type": "application/json"},
            json={"model": "jev-1.13.0", "state": state, "questions": questions},
            timeout=JEV_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("answers")
    except Exception as e:
        print(f" [AI] JEV决策异常: {e}")
        return None


def build_advice(decision: dict) -> str:
    """把 JEV 的结构化决策映射成一句实质性回复建议。"""
    if not decision:
        return None
    action = decision.get("action", {}).get("choice", "none")
    emotion = decision.get("emotion", {}).get("choice", "平静")
    base = ADVICE_MAP.get(action, ADVICE_MAP["none"])
    if emotion in ("难过", "生气", "疲惫"):
        base += "；TA情绪不好，语气放软，别皮"
    elif emotion == "调侃" and action != "play_along":
        base += "；对方在开玩笑，可以带点玩笑感回"
    elif emotion == "阴阳怪气":
        base += "；对方话里有刺，别接错了当真话回"
    return base


def extract_focus(decision: dict):
    """从 reading_* 答案里挑最贴合的事件卡。"""
    if not decision:
        return None
    best = None
    for card in EVENT_CARDS:
        ans = decision.get(f"reading_{card['id']}")
        if not ans:
            continue
        probs = ans.get("probabilities", {})
        p_sig = probs.get("signal", 0.0)
        if ans.get("choice") == "signal" and p_sig >= 0.5 and (best is None or p_sig > best["p_signal"]):
            best = {**card, "p_signal": p_sig, "p_ordinary": probs.get("ordinary", 0.0)}
    return best


def build_system_prompt(sentiment: int = None, decision: dict = None) -> str:
    """组合系统提示词：人设 + 关系沟通知识 + 情绪/意图引导。"""
    parts = [PERSONA]
    knowledge = RELATIONSHIP_KNOWLEDGE.get(RELATIONSHIP, f"对方和你的关系是：{RELATIONSHIP}。")
    parts.append(knowledge)
    if RELATIONSHIP_CONTEXT:
        parts.append(f"补充背景：{RELATIONSHIP_CONTEXT}")
    if decision:
        emo = decision.get("emotion", {})
        intent = decision.get("intent", {})
        probs = emo.get("probabilities", {})
        prob_str = "、".join(f"{k}{v:.0%}" for k, v in probs.items() if v > 0.05)
        progress = decision.get("progress", {}).get("choice", "sharing")
        progress_label = PROGRESS_LABELS.get(progress, progress)
        advice = build_advice(decision)
        parts.append(
            f"【军师决策】情绪「{emo.get('choice', '平静')}」（{prob_str}），"
            f"意图「{intent.get('choice', '分享')}」，对话阶段：{progress_label}。"
            f"回复策略：{advice}"
        )
        focus = extract_focus(decision)
        if focus:
            parts.append(
                f"【事件解读】{focus['question']} → {focus['signal']}（{focus['p_signal']:.0%}）。"
                "回复要贴合这个解读，不要答偏。"
            )
        mapped = JEV_EMOTION_TO_SENTIMENT.get(emo.get("choice"), 1)
        parts.append(EMOTION_GUIDE[mapped])
    elif sentiment in EMOTION_GUIDE:
        parts.append(EMOTION_GUIDE[sentiment])
    parts.append("如果对方发送的是[表情包]或[图片]，根据上下文猜测对方想表达什么，用幽默的方式回应。")
    return "\n".join(parts)


def get_ai_reply(last_message: str, conversation_history: list = None,
                 self_name: str = None, other_name: str = None,
                 force_reply: bool = False) -> str:
    """生成 AI 回复：JEV 决策优先，失败降级 BERT 情感，然后调 DeepSeek。
    self_name / other_name 用于把对话历史正确映射成 user/assistant 角色。
    force_reply=True 时跳过 JEV 回复门控（如群聊被 @ 时强制回复），但仍用 JEV 分析情绪/动作。
    返回回复文本；API 失败时返回兜底话术。"""
    self_name = self_name or AR_SELF_NICKNAME
    other_name = other_name or AR_TARGET_CONTACT

    decision = jev_decide(last_message, conversation_history)
    sentiment = None
    if decision:
        if not force_reply:
            p_reply = decision.get("should_reply", {}).get("noul", 1.0)
            if p_reply < JEV_MIN_REPLY_PROB:
                return None  # JEV 判定不适合回复，由调用方决定是否跳过
    else:
        sentiment = predict_sentiment(last_message)

    url = "https://api.deepseek.com/v1/chat/completions"
    messages = [{"role": "system", "content": build_system_prompt(sentiment, decision)}]
    if conversation_history:
        for msg in conversation_history[-MAX_HISTORY:]:
            if msg['sender'] == other_name:
                messages.append({"role": "user", "content": msg['text']})
            elif msg['sender'] == self_name:
                messages.append({"role": "assistant", "content": msg['text']})
    messages.append({"role": "user", "content": last_message})

    data = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": 200,
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        return reply.strip()
    except Exception as e:
        print(f" [AI] DeepSeek API异常: {e}")
        return random.choice(["网络不好~", "没听清，再说一遍？"])
