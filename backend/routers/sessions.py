"""sessions.py — 会话管理接口（需登录，按用户隔离）"""
from fastapi import APIRouter, HTTPException

from backend import db
from backend import auth
from backend.schemas import SessionCreateRequest, SessionItem, MessageItem

router = APIRouter()


@router.get("/api/sessions", response_model=list[SessionItem])
def list_sessions(user: dict = auth.require_user):
    return db.list_sessions(user["user_id"])


@router.post("/api/sessions", response_model=SessionItem)
def create_session(req: SessionCreateRequest, user: dict = auth.require_user):
    return db.create_session(user["user_id"], req.title)


@router.get("/api/sessions/{session_id}/messages", response_model=list[MessageItem])
def get_messages(session_id: str, user: dict = auth.require_user):
    msgs = db.get_messages(session_id, user["user_id"])
    if msgs is None:
        # 用 404 而非 403，避免泄露"该会话是否存在"
        raise HTTPException(status_code=404, detail="会话不存在")
    return msgs


@router.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, user: dict = auth.require_user):
    ok = db.delete_session(session_id, user["user_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}
