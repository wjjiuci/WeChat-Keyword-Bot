"""微信群聊机器人主程序。

架构（三队列 + 双线程，主线程永不阻塞）：
  主线程: wxauto 轮询 → 解析 → inbox_queue
          outbox_queue → 发送回复（群聊可 @对方）
  OCR 线程: inbox → 图片OCR → process_queue
  回复线程: process → 关键词/AI → outbox_queue

群聊机制：
  - 不是每条消息都回，需满足触发条件（@我 / 含触发词）
  - 防刷屏：同群两次回复最小间隔 GROUP_REPLY_INTERVAL 秒
  - 回复时可 @对方
"""
import time
import sys
import os
import re
import queue
import threading
from collections import defaultdict, deque

from wxauto import WeChat

try:
    from config import (
        WHITELIST, RULES, POLL_INTERVAL, SELF_NICKNAME,
        ENABLE_AI_REPLY, OCR_ENABLED,
        TRIGGER_MODE, GROUP_TRIGGER_KEYWORDS, GROUP_REPLY_INTERVAL, REPLY_WITH_AT,
        EMPTY_AT_REPLY, ZHIPU_API_KEY,
    )
except ImportError:
    try:
        from config import (
            WHITELIST, RULES, POLL_INTERVAL, SELF_NICKNAME,
            ENABLE_AI_REPLY, OCR_ENABLED,
        )
        TRIGGER_MODE = "at_or_kw"
        GROUP_TRIGGER_KEYWORDS = ["机器人", "小助手"]
        GROUP_REPLY_INTERVAL = 5.0
        REPLY_WITH_AT = True
        EMPTY_AT_REPLY = "在的，说啥？"
        ZHIPU_API_KEY = ""
    except ImportError:
        sys.exit("缺少 config.py：请复制 config.example.py 为 config.py 并填写白名单和规则")

from database import init_db, log_message
from matcher import match_rule, render_reply
from ocr import download_and_ocr
from commands import COMMANDS, Context, dispatch, resolve_command

if ENABLE_AI_REPLY:
    import ai_reply


# -------------------- 消息解析 --------------------

# 微信 @ 提及附近常见的特殊空白/不可见字符（U+2005 四分之一全角空格、NBSP、零宽空格等）
_WS_RE = re.compile(r"[\u00a0\u1680\u2000-\u200f\u2028\u2029\u202f\u205f\u3000\ufeff]+")


def _norm_ws(text):
    """把各种 Unicode 特殊空白统一成普通空格，避免 '@小明' 被不可见字符隔断导致漏判。"""
    return _WS_RE.sub(" ", text or "")


def _self_nicknames():
    """自身昵称列表（SELF_NICKNAME 支持 str / list / tuple，兼容多人备注场景）。"""
    nick = SELF_NICKNAME
    if isinstance(nick, (list, tuple, set)):
        return [str(n).strip() for n in nick if str(n).strip()]
    return [str(nick).strip()] if nick else []


def text_has_at_me(text):
    """纯文本信号：规范化空白后检查是否出现 @我的任一昵称。
    昵称后必须是边界（结尾/空白/标点），防止短昵称误吃长昵称，如 '@小明' 误判 '@小明林'。
    （微信原生 @ 后会自动插入空格，无分隔的 '@小明时间' 本就不是真 @；
     控件信号 detect_at_me 不受此限制，仍可精确识别。）"""
    norm = _norm_ws(text)
    for nick in _self_nicknames():
        pattern = re.compile(r"@" + re.escape(nick) + r"(?![\w一-鿿])")
        if pattern.search(norm):
            return True
    return False


def detect_at_me(raw_msg, content):
    """识别群消息是否 @ 了我，双信号：
    1) 文本信号：content 规范化空白后含 '@昵称'
    2) 控件信号：微信 UIA 中 @ 提及是消息气泡内的独立子控件，遍历子控件 Name
       （该信号不依赖文本拼接格式，兼容昵称含特殊字符、@后紧跟内容等情况）
    必须在主线程、消息控件仍有效时调用。
    """
    if text_has_at_me(content):
        return True

    if raw_msg is None:
        return False
    control = getattr(raw_msg, "control", None)
    if control is None:
        return False
    try:
        for sub in control.FindAll():
            name = _norm_ws(getattr(sub, "Name", "")).strip()
            # 真正的 @ 元素 Name 以 @ 开头（如 '@小明'）；普通文本子控件不会以 @ 开头
            if name.startswith("@") and any(name == f"@{nick}" or
                                            name.startswith(f"@{nick} ") for nick in _self_nicknames()):
                return True
    except Exception as e:
        print(f" [@检测] 子控件遍历失败，已忽略: {e}")
    return False


def parse_message(msg):
    """解析 wxauto 消息 → (sender, content, is_self, msg_type)。"""
    msg_type_name = type(msg).__name__

    if msg_type_name.startswith("Self") and "Message" in msg_type_name:
        content = getattr(msg, "content", "") or ""
        return (SELF_NICKNAME, content.strip(), True, "text")

    if msg_type_name.startswith("Friend") and "Message" in msg_type_name:
        sender = getattr(msg, "sender", None) or getattr(msg, "sender_remark", "未知")
        content = getattr(msg, "content", "") or ""
        if "Image" in msg_type_name:
            return (sender, content, False, "image")
        if "Emotion" in msg_type_name:
            return (sender, content or "[表情包]", False, "emotion")
        if "Voice" in msg_type_name:
            return (sender, content or "[语音]", False, "voice")
        if "File" in msg_type_name:
            return (sender, content or "[文件]", False, "file")
        if "Video" in msg_type_name:
            return (sender, content or "[视频]", False, "video")
        if not content:
            content = f"[{msg_type_name.replace('Friend', '').replace('Message', '')}]"
        return (sender, content.strip(), False, "text")

    if msg_type_name in ("TimeMessage", "SystemMessage", "TickleMessage"):
        return ("SYS", "[系统]", False, "sys")

    content = getattr(msg, "content", getattr(msg, "text", str(msg)))
    return ("unknown", str(content).strip(), False, "other")


# -------------------- 群聊触发判断 --------------------

def is_triggered(content, is_group, chat_type, at_me_hint=False):
    """判断群聊消息是否触发回复，返回 (是否触发, 是否@我)。
    - 私聊：永远触发
    - 群聊：@我 / 含触发词 / 以 # 开头的命令
    at_me_hint：主线程基于 UIA 子控件检测出的 @我 信号，与文本信号取或
    """
    if not is_group:
        return True, False  # 私聊全回复

    text = _norm_ws(content or "")
    at_me = at_me_hint or text_has_at_me(content)
    is_command = text.strip().startswith("#")
    has_keyword = any(_norm_ws(kw).strip() in text for kw in GROUP_TRIGGER_KEYWORDS)

    if TRIGGER_MODE == "at":
        return at_me or is_command, at_me
    if TRIGGER_MODE == "keyword":
        return has_keyword or is_command, at_me
    # at_or_kw
    return at_me or has_keyword or is_command, at_me


def clean_content(content, is_group):
    """去掉消息里的 @我 部分，返回用于规则匹配 / AI 理解的干净文本。
    例：'@小明 时间' -> '时间'。先规范化特殊空白，再带昵称边界移除 @，避免误伤 '@小明林'。"""
    text = _norm_ws(content or "").strip()
    if is_group:
        for nick in _self_nicknames():
            pattern = re.compile(r"@" + re.escape(nick) + r"(?![\w一-鿿])")
            text = pattern.sub(" ", text)
        text = " ".join(text.split())  # 合并多余空白
    return text


# -------------------- OCR 线程 --------------------

def ocr_worker(inbox_q, process_q, stop_event):
    while not stop_event.is_set():
        try:
            item = inbox_q.get(timeout=1.0)
        except queue.Empty:
            continue
        chat, sender, content, is_self, msg_type, at_me, raw_msg = item
        try:
            if msg_type == "image" and OCR_ENABLED and raw_msg is not None:
                ocr_text = download_and_ocr(raw_msg)
                normalized = f"[图片] {ocr_text}" if ocr_text else "[图片]"
            else:
                normalized = content
            process_q.put((chat, sender, normalized, is_self, at_me, raw_msg))
        except Exception as e:
            print(f" [OCR线程] 处理异常: {e}")
            process_q.put((chat, sender, content or "[图片]", is_self, at_me, raw_msg))
        finally:
            inbox_q.task_done()


# -------------------- 回复线程 --------------------

def reply_worker(process_q, outbox_q, conn, history, group_cache, last_reply_time, stop_event):
    while not stop_event.is_set():
        try:
            chat, sender, content, is_self, at_me_hint, raw_msg = process_q.get(timeout=1.0)
        except queue.Empty:
            continue

        try:
            log_message(conn, chat, sender, content, is_self)

            if is_self:
                history[chat].append({"sender": SELF_NICKNAME, "text": content})
                continue

            # 群聊触发判断（at_me_hint 为主线程 UIA 子控件检测结果）
            is_group = group_cache.get(chat, False)
            if is_group:
                triggered, at_me = is_triggered(content, True, None, at_me_hint=at_me_hint)
                if not triggered:
                    # 群聊未触发：只记录，不回复
                    history[chat].append({"sender": sender, "text": content})
                    continue
            else:
                at_me = False

            # 清洗 @ 前缀，得到干净文本（用于规则匹配和 AI 理解）
            cleaned = clean_content(content, is_group)

            # 群聊防刷屏
            if is_group:
                now = time.time()
                last = last_reply_time.get(chat, 0)
                if now - last < GROUP_REPLY_INTERVAL:
                    history[chat].append({"sender": sender, "text": content})
                    continue

            # 0) 群里只 @ 我但没说话 → 固定回应
            if is_group and at_me and not cleaned:
                if EMPTY_AT_REPLY:
                    ts = time.strftime("%H:%M:%S")
                    print(f"[{ts}] [{chat}] {sender}: {content}")
                    print(f"        ↳ 只@我没说话 → {EMPTY_AT_REPLY}")
                    outbox_q.put((chat, sender, content, EMPTY_AT_REPLY, "[空@]", raw_msg, is_group, None))
                    history[chat].append({"sender": sender, "text": content})
                    history[chat].append({"sender": SELF_NICKNAME, "text": EMPTY_AT_REPLY})
                    last_reply_time[chat] = time.time()
                else:
                    history[chat].append({"sender": sender, "text": content})
                continue

            # 1) 命令插件：
            #    a) '#帮助'、'@小明 #天气 北京'（清洗后以 # 开头）
            #    b) '@小明 帮助'、'@小明 天气 北京'、'@小明 天气吉安'（@我后直接跟命令名/别名，无需 #）
            cmd_text = None
            if cleaned.startswith("#"):
                cmd_text = cleaned
            elif is_group and at_me and cleaned:
                bare_entry, _ = resolve_command(cleaned)
                if bare_entry is not None:
                    cmd_text = "#" + cleaned

            if cmd_text is not None:
                # 异步投递回调（#画图 等命令在后台线程生成完后，通过出箱队列交给主线程发送）
                def _deliver_text(text_extra, _chat=chat, _sender=sender, _raw=raw_msg, _grp=is_group):
                    outbox_q.put((_chat, _sender, content, text_extra, "[异步]", _raw, _grp, None))

                def _deliver_image(path, caption="", _chat=chat, _sender=sender, _raw=raw_msg, _grp=is_group):
                    outbox_q.put((_chat, _sender, content, caption, "[画图]", _raw, _grp, path))

                cmd_ctx = Context(chat=chat, sender=sender, content=cmd_text,
                                  arg="", is_group=is_group,
                                  deliver_text=_deliver_text, deliver_image=_deliver_image)
                handled, cmd_reply = dispatch(cmd_text, cmd_ctx)
                if handled:
                    if cmd_reply:
                        cmd_tag = "#" + cmd_text[1:].split(maxsplit=1)[0]
                        ts = time.strftime("%H:%M:%S")
                        print(f"[{ts}] [{chat}] {sender}: {content}")
                        print(f"        ↳ 指令 {cmd_tag} → {cmd_reply.replace(chr(10), ' / ')}")
                        outbox_q.put((chat, sender, content, cmd_reply, cmd_tag, raw_msg, is_group, None))
                        history[chat].append({"sender": sender, "text": content})
                        history[chat].append({"sender": SELF_NICKNAME, "text": cmd_reply})
                        last_reply_time[chat] = time.time()
                    continue  # 未知命令/空回复也不往下走 AI

            # 2) 关键词匹配（用清洗后的文本，'@小明 时间' 也能命中）
            rule, reply_tpl = match_rule(cleaned, RULES)
            if rule:
                reply = render_reply(reply_tpl, sender=sender, chat=chat, content=content)
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] [{chat}] {sender}: {content}")
                print(f"        ↳ 关键词命中「{rule['match']}」→ {reply}")
                outbox_q.put((chat, sender, content, reply, rule["match"], raw_msg, is_group, None))
                history[chat].append({"sender": sender, "text": content})
                history[chat].append({"sender": SELF_NICKNAME, "text": reply})
                last_reply_time[chat] = time.time()
                continue

            # 3) AI 兜底
            if ENABLE_AI_REPLY:
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] [{chat}] {sender}: {content}")
                print(f"        ↳ 无关键词命中，调用 AI 回复...")
                try:
                    reply = ai_reply.get_ai_reply(
                        cleaned or content,
                        conversation_history=list(history[chat]),
                        self_name=SELF_NICKNAME,
                        other_name=sender,
                        force_reply=at_me,  # 被 @ 时强制回复，跳过 JEV 门控
                    )
                except Exception as e:
                    print(f"        ↳ AI 回复异常: {e}")
                    reply = None

                if reply is None:
                    print(f"        ↳ AI 判定不适合回复，跳过")
                    history[chat].append({"sender": sender, "text": content})
                    continue

                print(f"        ↳ AI 回复: {reply}")
                outbox_q.put((chat, sender, content, reply, "[AI]", raw_msg, is_group, None))
                history[chat].append({"sender": sender, "text": content})
                history[chat].append({"sender": SELF_NICKNAME, "text": reply})
                last_reply_time[chat] = time.time()
            else:
                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] [{chat}] {sender}: {content}  (无匹配，AI已关闭)")
        except Exception as e:
            print(f" [回复线程] 处理异常: {e}")
        finally:
            process_q.task_done()


def _update_trigger_message(conn, chat, sender, content, matched_rule, reply):
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM messages WHERE chat_name=? AND sender=? AND content=? "
        "ORDER BY id DESC LIMIT 1",
        (chat, sender, content),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE messages SET matched_rule=?, reply=?, replied_at=? WHERE id=?",
            (matched_rule, reply, time.strftime("%Y-%m-%d %H:%M:%S"), row[0]),
        )
        conn.commit()


# -------------------- 主线程 --------------------

def main():
    if not WHITELIST:
        sys.exit("白名单为空，请在 config.py 的 WHITELIST 里填入要监听的群名")

    print("正在连接微信...")
    wx = WeChat()
    print("微信连接成功")

    conn = init_db()

    inbox_q = queue.Queue(maxsize=200)
    process_q = queue.Queue(maxsize=200)
    outbox_q = queue.Queue(maxsize=200)

    stop_event = threading.Event()
    history = defaultdict(lambda: deque(maxlen=12))
    group_cache = {}            # chat -> is_group
    last_reply_time = {}        # chat -> 最后回复时间戳（防刷屏）
    seen = defaultdict(set)
    MAX_SEEN = 3000
    baseline = defaultdict(set)   # 启动时的历史消息基线，永不裁剪，防止旧消息“复活”误报

    ocr_thread = threading.Thread(
        target=ocr_worker, args=(inbox_q, process_q, stop_event), daemon=True
    )
    reply_thread = threading.Thread(
        target=reply_worker,
        args=(process_q, outbox_q, conn, history, group_cache, last_reply_time, stop_event),
        daemon=True,
    )
    ocr_thread.start()
    reply_thread.start()

    print(f"白名单：{WHITELIST}")
    print(f"触发模式：{TRIGGER_MODE}  |  触发词：{GROUP_TRIGGER_KEYWORDS}")
    print(f"防刷屏间隔：{GROUP_REPLY_INTERVAL}s  |  @回复：{'开' if REPLY_WITH_AT else '关'}")
    _cmd_count = len({id(e) for e in COMMANDS.values()})
    print(f"指令插件：{_cmd_count} 个  |  关键词规则：{len(RULES)} 条  |  AI：{'开' if ENABLE_AI_REPLY else '关'}  |  OCR：{'开' if OCR_ENABLED else '关'}  |  画图：{'智谱CogView' if ZHIPU_API_KEY else '免费接口'}")
    print("-" * 60)

    # ---------- 历史预热：把启动前已存在的消息全部标记为“已见”，不回复、不入上下文 ----------
    # 否则首次 GetAllMessage() 会把整屏历史当新消息处理，造成误报
    for chat in WHITELIST:
        try:
            wx.ChatWith(chat)
            time.sleep(0.5)
            old_messages = wx.GetAllMessage()
        except Exception as e:
            print(f"[历史预热失败] {chat}: {e}")
            continue

        # 顺便缓存群聊类型
        if chat not in group_cache:
            try:
                group_cache[chat] = (wx.chat_type == "group")
            except Exception:
                group_cache[chat] = False

        count = 0
        for msg in old_messages:
            sender, content, is_self, msg_type = parse_message(msg)
            if sender == "SYS" or not content:
                continue
            baseline[chat].add(f"{sender}::{content}")
            count += 1
        print(f"  [{chat}] 已忽略 {count} 条历史消息，只响应启动后的新消息")
    print("-" * 60)

    try:
        while not stop_event.is_set():
            for chat in WHITELIST:
                # 轮询消息
                try:
                    wx.ChatWith(chat)
                    time.sleep(0.4)
                    messages = wx.GetAllMessage()
                except Exception as e:
                    print(f"[读取失败] {chat}: {e}")
                    messages = []

                # 检测是否群聊（只检测一次，缓存）
                if chat not in group_cache:
                    try:
                        ct = wx.chat_type
                        group_cache[chat] = (ct == "group")
                        print(f"  [{chat}] 类型: {'群聊' if group_cache[chat] else '私聊'}")
                    except Exception:
                        group_cache[chat] = False

                for msg in messages:
                    sender, content, is_self, msg_type = parse_message(msg)
                    if sender == "SYS" or not content:
                        continue

                    key = f"{sender}::{content}"
                    if key in seen[chat] or key in baseline[chat]:
                        continue
                    seen[chat].add(key)
                    if len(seen[chat]) > MAX_SEEN:
                        half = list(seen[chat])[MAX_SEEN // 2:]
                        seen[chat] = set(half)

                    # 群聊且非本人消息：在主线程控件有效时检测 @我（文本 + UIA 子控件双信号）
                    is_group_now = group_cache.get(chat, False)
                    at_me = (not is_self and is_group_now
                             and detect_at_me(msg, content))

                    raw_msg = msg if msg_type == "image" else None
                    try:
                        inbox_q.put_nowait(
                            (chat, sender, content, is_self, msg_type, at_me, raw_msg)
                        )
                    except queue.Full:
                        print(f" [警告] inbox 队列已满，丢弃: {content[:20]}")

                # 发送待回复（元组末位 image_path 非 None 时发图片，否则发文本）
                while True:
                    try:
                        chat_r, sender_r, content_r, reply, matched_rule, raw_msg, is_group, image_path = outbox_q.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        if chat_r != chat:
                            wx.ChatWith(chat_r)
                            time.sleep(0.3)

                        if image_path:
                            # 图片发送（如 #画图 产物）
                            if is_group and REPLY_WITH_AT and sender_r:
                                try:
                                    wx.SendMsg(f"@{sender_r} {reply or '画好了~'}")
                                except Exception:
                                    pass
                            wx.SendFiles(image_path, who=chat_r)
                            log_message(conn, chat_r, SELF_NICKNAME,
                                        f"[图片] {os.path.basename(image_path)}", is_self=True)
                            try:
                                os.remove(image_path)
                            except Exception:
                                pass
                        else:
                            # 群聊 @回复
                            if is_group and REPLY_WITH_AT and raw_msg is not None:
                                try:
                                    raw_msg.at(reply)
                                except Exception:
                                    wx.SendMsg(f"@{sender_r} {reply}")
                            else:
                                wx.SendMsg(reply)
                            log_message(conn, chat_r, SELF_NICKNAME, reply, is_self=True)
                            _update_trigger_message(conn, chat_r, sender_r, content_r, matched_rule, reply)
                    except Exception as e:
                        print(f" [发送失败] {chat_r}: {e}")
                    finally:
                        outbox_q.task_done()

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n正在停止...")
        stop_event.set()
        ocr_thread.join(timeout=3)
        reply_thread.join(timeout=3)
        print("程序退出")


if __name__ == "__main__":
    main()
