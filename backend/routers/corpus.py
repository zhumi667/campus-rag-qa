"""backend/routers/corpus.py — 面向已登录用户的语料目录（只读）

★ 与 /api/admin/* 的区别：本路由只暴露"库里有哪些资料"，不暴露文件路径、
  不提供任何写操作。目的是让学生能自行确认"我要问的文件在不在库里"，
  从而减少问到未收录内容后得到拒答的挫败感。
"""
from fastapi import APIRouter

from backend import auth
from src import corpus_admin as ca

router = APIRouter(prefix="/api/corpus", tags=["corpus"])


@router.get("/docs")
def list_public_docs(user: dict = auth.require_user):
    """已收录资料清单，只返回当前有效的文档。

    · 只返回展示所需字段，不含 raw_path / text_path / 文件存在性等内部信息
    · status 非 active 的文档不返回，与检索期的版本过滤保持一致，
      避免出现"学生看得到、提问却检索不到"的矛盾
    """
    out = []
    for d in ca.list_docs():
        if (d.get("status") or "").strip().lower() != "active":
            continue
        out.append({
            "title": d.get("title", ""),
            "family_id": d.get("family_id", ""),
            "version": d.get("version", ""),
            "effective_date": d.get("effective_date", ""),
            "chars": d.get("chars", 0),
        })
    return out
