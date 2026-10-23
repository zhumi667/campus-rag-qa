"""db.py — SQLite 存储（标准库 sqlite3，无 ORM）

数据库文件 data/db/app.db（已加入 .gitignore）。

★ 说明：data/db/app.db 可安全删除，重启后端会自动重建（表结构与默认用户
  都在 init_db() / seed_default_users() 中定义）。
★ 路径统一由 config.DB_PATH 提供，本文件不再自行拼接。
"""
import json
import secrets
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import config

DB_PATH = config.DB_PATH


def _now() -> str:
    return datetime.now().isoformat()


def _conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # WAL：读写可并发。问答时会频繁写入会话历史，默认 rollback journal 下读写互斥，
    # 会偶发 "database is locked"，开启 WAL 后读写不再互相阻塞。
    conn.execute("PRAGMA journal_mode=WAL")
    # 锁等待 5 秒而非立即报错（配合 WAL，进一步降低并发写冲突）。
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _public_user(row) -> dict:
    """把用户行转成对外返回的 dict（剔除 password_hash / salt）"""
    d = dict(row)
    d.pop("password_hash", None)
    d.pop("salt", None)
    return d


def init_db() -> None:
    """数据库结构的【唯一来源】。

    表结构必须在此定义，不得使用 Navicat 等外部工具手工建表或改表 ——
    否则数据库将无法通过删除 data/db/app.db 重建，换机器即失效。
    外部工具仅用于【查看】数据。
    """
    with closing(_conn()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                sources TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       TEXT PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt          TEXT NOT NULL,
                role          TEXT NOT NULL,
                display_name  TEXT,
                created_at    TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                token      TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                created_at TEXT,
                expires_at TEXT
            )
        """)
        # 语料导入记录（管理员「语料导入」功能，2026-10-04 新增）
        # 记录每次导入的文档、操作人、流水线执行结果；与 documents.csv 相互印证
        conn.execute("""
            CREATE TABLE IF NOT EXISTS corpus_imports (
                import_id     TEXT PRIMARY KEY,
                doc_id        TEXT,
                source_name   TEXT,
                file_size     INTEGER,
                status        TEXT,
                stage         TEXT,
                message       TEXT,
                scan_json     TEXT,
                detail_json   TEXT,
                user_id       TEXT,
                created_at    TEXT,
                updated_at    TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_imports_doc ON corpus_imports(doc_id)")
        # 幂等迁移：给 sessions 补 user_id 字段（已存在则跳过）
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)")]
        if "user_id" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
        conn.commit()


# ------------------------------------------------------------
# 用户
# ------------------------------------------------------------
def seed_default_users() -> dict:
    """创建预置演示账号（已存在则跳过），并把无归属的历史会话归给 admin。

    返回 {"admin": bool, "student": bool}，bool 表示是否为本次新建。
    """
    result = {"admin": False, "student": False}
    if get_user_by_username("admin") is None:
        create_user("admin", "admin123", "admin", "管理员")
        result["admin"] = True
    if get_user_by_username("student") is None:
        create_user("student", "student123", "student", "学生")
        result["student"] = True

    # 迁移：历史会话（无 user_id）归 admin，保证数据不丢失
    admin = get_user_by_username("admin")
    if admin:
        with closing(_conn()) as conn:
            conn.execute(
                "UPDATE sessions SET user_id=? WHERE user_id IS NULL",
                (admin["user_id"],),
            )
            conn.commit()
    return result


def create_user(username: str, password: str, role: str, display_name: str = None) -> dict | None:
    """创建用户。用户名已存在返回 None。"""
    from backend import auth  # 延迟 import 避免循环依赖

    if get_user_by_username(username) is not None:
        return None
    hash_b64, salt_b64 = auth.hash_password(password)
    user_id = uuid.uuid4().hex
    now = _now()
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, salt, role, display_name, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (user_id, username, hash_b64, salt_b64, role, display_name, now),
        )
        conn.commit()
    return {"user_id": user_id, "username": username, "role": role,
            "display_name": display_name, "created_at": now}


def get_user_by_username(username: str) -> dict | None:
    with closing(_conn()) as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with closing(_conn()) as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def verify_password(username: str, password: str) -> dict | None:
    """校验用户名密码，成功返回不含 hash/salt 的用户 dict，失败返回 None。"""
    from backend import auth  # 延迟 import 避免循环依赖

    u = get_user_by_username(username)
    if u is None:
        return None
    if not auth.check_password(password, u["password_hash"], u["salt"]):
        return None
    return _public_user(u)


# ------------------------------------------------------------
# 令牌
# ------------------------------------------------------------
def create_token(user_id: str, ttl_days: int = 7) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires = now + timedelta(days=ttl_days)
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO tokens (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, user_id, now.isoformat(), expires.isoformat()),
        )
        conn.commit()
    return token


def get_token_user(token: str) -> dict | None:
    """根据 token 取用户（不含 hash/salt）。过期则删除该 token 并返回 None。"""
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT u.user_id, u.username, u.role, u.display_name, t.expires_at "
            "FROM tokens t JOIN users u ON t.user_id = u.user_id WHERE t.token=?",
            (token,),
        ).fetchone()
    if row is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < datetime.now():
        delete_token(token)
        return None
    return {"user_id": row["user_id"], "username": row["username"],
            "role": row["role"], "display_name": row["display_name"]}


def delete_token(token: str) -> None:
    with closing(_conn()) as conn:
        conn.execute("DELETE FROM tokens WHERE token=?", (token,))
        conn.commit()


def purge_expired_tokens() -> int:
    with closing(_conn()) as conn:
        cur = conn.execute("DELETE FROM tokens WHERE expires_at < ?", (_now(),))
        conn.commit()
        return cur.rowcount


# ------------------------------------------------------------
# 会话（按用户隔离）
# ------------------------------------------------------------
def create_session(user_id: str, title: str | None = None) -> dict:
    sid = uuid.uuid4().hex
    title = title or "新对话"
    now = _now()
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, user_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
            (sid, user_id, title, now, now),
        )
        conn.commit()
    return {"session_id": sid, "title": title, "created_at": now, "updated_at": now}


def list_sessions(user_id: str) -> list:
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_messages(session_id: str, user_id: str) -> list | None:
    """返回该会话消息；会话不存在或不属于该用户返回 None。"""
    with closing(_conn()) as conn:
        owner = conn.execute("SELECT user_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if owner is None or owner["user_id"] != user_id:
            return None
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY id ASC", (session_id,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("id", None)
        d["sources"] = json.loads(d["sources"]) if d.get("sources") else []
        result.append(d)
    return result


def add_message(session_id: str, role: str, content: str, sources: list = None) -> None:
    now = _now()
    sources_json = json.dumps(sources or [], ensure_ascii=False)
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, sources, created_at) VALUES (?,?,?,?,?)",
            (session_id, role, content, sources_json, now),
        )
        conn.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (now, session_id))
        conn.commit()


def delete_session(session_id: str, user_id: str) -> bool:
    """删除会话及其消息；会话不存在或不属于该用户返回 False。"""
    with closing(_conn()) as conn:
        owner = conn.execute("SELECT user_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        if owner is None or owner["user_id"] != user_id:
            return False
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        conn.commit()
        return True


def session_belongs_to(session_id: str, user_id: str) -> bool:
    """判断会话是否属于该用户（问答写历史前校验归属）。"""
    with closing(_conn()) as conn:
        owner = conn.execute("SELECT user_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    return owner is not None and owner["user_id"] == user_id


# ------------------------------------------------------------
# 语料导入记录（管理员功能）
# ------------------------------------------------------------
def create_import(import_id: str, source_name: str, file_size: int,
                  user_id: str, doc_id: str = "", scan: dict = None) -> None:
    """新建一条导入记录，状态 pending。"""
    now = _now()
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO corpus_imports "
            "(import_id, doc_id, source_name, file_size, status, stage, message,"
            " scan_json, detail_json, user_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (import_id, doc_id, source_name, file_size, "pending", "staged",
             "已上传，等待管理员确认", json.dumps(scan or {}, ensure_ascii=False),
             "{}", user_id, now, now),
        )
        conn.commit()


def update_import(import_id: str, *, status: str = None, stage: str = None,
                  message: str = None, doc_id: str = None,
                  detail: dict = None) -> None:
    """更新导入记录（只更新传入的字段）。"""
    sets, vals = ["updated_at=?"], [_now()]
    if status is not None:
        sets.append("status=?"); vals.append(status)
    if stage is not None:
        sets.append("stage=?"); vals.append(stage)
    if message is not None:
        sets.append("message=?"); vals.append(message)
    if doc_id is not None:
        sets.append("doc_id=?"); vals.append(doc_id)
    if detail is not None:
        sets.append("detail_json=?"); vals.append(json.dumps(detail, ensure_ascii=False))
    vals.append(import_id)
    with closing(_conn()) as conn:
        conn.execute(f"UPDATE corpus_imports SET {', '.join(sets)} WHERE import_id=?", vals)
        conn.commit()


def list_imports(limit: int = 30) -> list:
    """最近的导入记录（新在前）。"""
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM corpus_imports ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for key, field in (("scan_json", "scan"), ("detail_json", "detail")):
            try:
                d[field] = json.loads(d.pop(key) or "{}")
            except Exception:
                d[field] = {}
        out.append(d)
    return out


def get_import(import_id: str) -> dict | None:
    with closing(_conn()) as conn:
        r = conn.execute(
            "SELECT * FROM corpus_imports WHERE import_id=?", (import_id,)
        ).fetchone()
    if r is None:
        return None
    d = dict(r)
    for key, field in (("scan_json", "scan"), ("detail_json", "detail")):
        try:
            d[field] = json.loads(d.pop(key) or "{}")
        except Exception:
            d[field] = {}
    return d
