"""chat.py — 问答接口（非流式 + SSE 流式，需登录）"""
import asyncio
import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from src.pipeline import QAPipeline
from backend.schemas import ChatRequest, ChatResponse
from backend import auth, db

router = APIRouter()


def _make_pipeline(req: ChatRequest) -> QAPipeline:
    return QAPipeline(top_k=req.top_k, use_llm_check=req.use_llm_check)


def _check_session(req: ChatRequest, user: dict) -> None:
    """带 session_id 时校验会话归属；不属于当前用户 → 404（不泄露会话是否存在）。"""
    if req.session_id and not db.session_belongs_to(req.session_id, user["user_id"]):
        raise HTTPException(status_code=404, detail="会话不存在")


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, user: dict = auth.require_user):
    """非流式问答（便于调试）"""
    _check_session(req, user)
    pipeline = _make_pipeline(req)
    result = pipeline.ask(req.question)
    if req.session_id:
        db.add_message(req.session_id, "user", req.question, [])
        db.add_message(req.session_id, "assistant", result["answer"], result["sources"])
    return result


@router.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, user: dict = auth.require_user):
    """SSE 流式问答（前端主用）。帧序：meta → token* → done（拒答时 meta → done）。"""
    _check_session(req, user)
    pipeline = _make_pipeline(req)

    async def gen():
        answer_parts = []
        sources = []
        try:
            for event in pipeline.ask_stream(req.question):
                et = event["type"]
                data = {k: v for k, v in event.items() if k != "type"}
                if et == "meta":
                    sources = event.get("sources", [])
                elif et == "token":
                    answer_parts.append(event.get("text", ""))
                elif et == "refused_override":
                    # 生成器侧拒答守卫生效：用规范话术替换已流出的文本，
                    # 并清空引用（没有答案就没有引用依据）。历史里也要存纠正后的内容，
                    # 否则回看会话时会看到"带引用的拒答话术"这一矛盾状态。
                    answer_parts = [event.get("answer", "")]
                    sources = []
                yield {"event": et, "data": json.dumps(data, ensure_ascii=False)}
            # 流正常结束，写会话历史（session_id 已校验归属）
            if req.session_id:
                db.add_message(req.session_id, "user", req.question, [])
                db.add_message(req.session_id, "assistant", "".join(answer_parts), sources)
        except asyncio.CancelledError:
            raise  # 客户端断开：正常取消，不打印栈
        except Exception as e:
            yield {"event": "error", "data": json.dumps({"message": str(e)}, ensure_ascii=False)}

    return EventSourceResponse(gen())
