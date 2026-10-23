"""auth.py — 密码哈希与令牌鉴权

★ 为什么不用 JWT：
  JWT 需要引入 python-jose / PyJWT 等第三方库；且 JWT 是无状态的，签发后无法服务端吊销
  （登出后旧 token 仍有效，直到自然过期）。本系统采用「服务端不透明令牌 + 数据库存储」，
  仅用标准库，登出即删除令牌、立即可吊销。

★ 为什么用 200k 次 PBKDF2：
  PBKDF2 通过大量迭代显著提高离线暴力破解成本。200,000 次是 OWASP 对 PBKDF2-SHA256 的
  推荐迭代数（截至 2023）；结合每用户独立 16 字节随机盐，可抵抗彩虹表与暴力破解。
"""
import base64
import hashlib
import hmac
import os

from fastapi import Depends, HTTPException, Request


def hash_password(password: str) -> tuple:
    """返回 (hash_b64, salt_b64)"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000)
    return base64.b64encode(dk).decode('ascii'), base64.b64encode(salt).decode('ascii')


def check_password(password: str, hash_b64: str, salt_b64: str) -> bool:
    """用 hmac.compare_digest 常量时间比较，防时序攻击。"""
    try:
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000)
    return hmac.compare_digest(dk, expected)


def get_current_user(request: Request) -> dict:
    """从 Authorization: Bearer <token> 取令牌并解析用户；无效/过期 → 401。"""
    auth_header = request.headers.get("Authorization", "")
    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")

    from backend import db  # 延迟 import 避免循环依赖
    user = db.get_token_user(token)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user


require_user = Depends(get_current_user)


def require_admin(request: Request) -> dict:
    """管理员依赖。

    用法：路由写成 `user: dict = Depends(require_admin)`。

    ★ 刻意写成「普通函数 + Request 形参」，而不是
      `def require_admin(user: dict = Depends(get_current_user))`：
      · 后者是普通函数，路由里若写成 `user = require_admin`（漏掉 Depends 包裹），
        FastAPI 会把它当作【普通参数默认值】直接以零参调用，user 拿到的是函数对象，
        user["role"] 报 TypeError；
      · 同理也不能写 `Depends(Depends(...))`。
      本写法只有一种正确用法，且漏包 Depends 时会被 FastAPI 明确报错而非静默错值。
    """
    user = get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
