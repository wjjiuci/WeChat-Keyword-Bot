"""SQLite 消息日志：记录每条消息的发送人、时间、内容，以及命中的规则和回复。"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages.db")


def init_db():
    """初始化数据库，返回连接对象。"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")  # 提升并发写入性能
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at   TEXT    NOT NULL,        -- 消息接收/发送时间
            chat_name     TEXT    NOT NULL,        -- 所在聊天（联系人或群名）
            sender        TEXT    NOT NULL,        -- 发送人昵称
            content       TEXT    NOT NULL,        -- 消息内容
            is_self       INTEGER NOT NULL DEFAULT 0,  -- 1=自己发的, 0=对方发的
            matched_rule  TEXT,                    -- 命中的规则（对方消息才有）
            reply         TEXT,                    -- 机器人的回复内容
            replied_at    TEXT                     -- 回复时间
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_time ON messages(chat_name, received_at)")
    conn.commit()
    return conn


def log_message(conn, chat_name, sender, content, is_self,
                matched_rule=None, reply=None):
    """写入一条消息日志，返回记录 id。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages (received_at, chat_name, sender, content, is_self, matched_rule, reply, replied_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (now, chat_name, sender, content, 1 if is_self else 0,
         matched_rule, reply, now if reply else None),
    )
    conn.commit()
    return c.lastrowid


def query_recent(conn, chat_name=None, limit=50):
    """查询最近的消息记录，返回字典列表。"""
    c = conn.cursor()
    if chat_name:
        c.execute(
            "SELECT * FROM messages WHERE chat_name = ? ORDER BY id DESC LIMIT ?",
            (chat_name, limit),
        )
    else:
        c.execute("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,))
    cols = [d[0] for d in c.description]
    return [dict(zip(cols, row)) for row in c.fetchall()]
