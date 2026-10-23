"""auth.py — 认证接口（登录 / 登出 / 当前用户）"""
import time

from fastapi import APIRouter, HTTPException, Request

from backend import auth as auth_mod
from backend import db
from backend.schemas import LoginRequest, LoginResponse, UserInfo

router = APIRouter()

# 登录失败锁定：username -> {"fail_count": int, "locked_until": float(时间戳)}
# 简单内存计数，连续失败 5 次锁定该用户名 60 秒；进程重启后清零。
_fail_log: dict = {}

_LOCK_THRESHOLD = 5
_LOCK_SECONDS = 60


def _is_locked(username: str) -> bool:
    rec = _fail_log.get(username)
    return bool(rec and rec["locked_until"] > time.time())


@router.post("/api/auth/login", response_model=LoginResponse)
def login(req: LoginRequest):
    if _is_locked(req.username):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user = db.verify_password(req.username, req.password)
    if user is None:
        # 不区分"用户不存在"与"密码错误"，避免枚举用户名
        rec = _fail_log.setdefault(req.username, {"fail_count": 0, "locked_until": 0.0})
        rec["fail_count"] += 1
        if rec["fail_count"] >= _LOCK_THRESHOLD:
            rec["locked_until"] = time.time() + _LOCK_SECONDS
            rec["fail_count"] = 0
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    _fail_log.pop(req.username, None)
    token = db.create_token(user["user_id"])
    return {"token": token, "user": user}


@router.post("/api/auth/logout")
def logout(request: Request, user: dict = auth_mod.require_user):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    if token:
        db.delete_token(token)
    return {"ok": True}


@router.get("/api/auth/me", response_model=UserInfo)
def me(user: dict = auth_mod.require_user):
    return user
