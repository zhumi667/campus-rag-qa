"""schemas.py — Pydantic 请求/响应模型"""
from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    top_k: int | None = None
    use_llm_check: bool = True


class SourceItem(BaseModel):
    idx: int
    chunk_id: str
    doc_id: str
    doc_title: str
    heading_path: str
    score: float
    char_start: int
    char_end: int
    snippet: str
    # snippet 是否因长度上限被截断（省略号已包含在 snippet 内；此字段供前端提示"已省略"）
    is_truncated: bool = False
    # ★ 来源文档的版本状态（检索期已按 status/生效日期过滤；
    #   这些字段用于前端展示"该引用来自哪个版本、何时生效"）
    status: str = ""
    version: str = ""
    family_id: str = ""
    effective_date: str = ""
    expire_date: str = ""


class ChatResponse(BaseModel):
    question: str
    answer: str
    refused: bool
    # 仅 refused=True 时有意义，取值：empty / threshold / llm / pass
    # （与 judge.stage 同义；显式声明以便前端直接读取，避免 FastAPI 静默过滤）
    refuse_stage: str = ""
    sources: list[SourceItem]          # 拒答时为空数组（没有答案就没有引用依据）
    retrieved: list[SourceItem] = []   # 检索候选，始终保留（供"为何未答"展示/调试）
    timing: dict
    judge: dict


class SessionCreateRequest(BaseModel):
    title: str | None = None


class SessionItem(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str


class MessageItem(BaseModel):
    role: str
    content: str
    created_at: str
    sources: list[SourceItem] = []


class HealthResponse(BaseModel):
    ok: bool
    ollama: dict
    index: dict
    corpus: dict


class LoginRequest(BaseModel):
    username: str
    password: str


class UserInfo(BaseModel):
    user_id: str
    username: str
    role: str
    display_name: str | None = None


class LoginResponse(BaseModel):
    token: str
    user: UserInfo


# ---------------------------------------------------------------- 语料导入（管理员）
class ScanHit(BaseModel):
    rule: str
    value: str
    context: str = ""


class ScanSummary(BaseModel):
    ok: bool
    text_len: int = 0
    block_count: int = 0
    warn_count: int = 0
    blocks: list[ScanHit] = []
    warns: list[ScanHit] = []


class StagingItem(BaseModel):
    staging_id: str
    filename: str
    size: int
    uploaded_at: str


class UploadResponse(BaseModel):
    staging_id: str
    filename: str
    size: int
    ext: str


class BatchUploadItem(BaseModel):
    ok: bool
    staging_id: str = ""
    filename: str
    size: int = 0
    ext: str = ""
    error: str = ""


class BatchUploadResponse(BaseModel):
    total: int
    ok_count: int
    items: list[BatchUploadItem] = []


class PreviewResponse(BaseModel):
    staging_id: str
    filename: str
    file_type: str
    text_len: int
    paragraph_count: int
    table_count: int
    sample: str
    scan: ScanSummary
    suggested_doc_id: str
    suggested_title: str
    error: str = ""


class ImportMeta(BaseModel):
    doc_id: str
    title: str
    family_id: str
    version: str
    issuer: str = ""
    publish_date: str = ""
    effective_date: str = ""
    expire_date: str = ""
    source_url: str = ""
    file_type: str
    status: str = "active"
    notes: str = ""
    # 覆盖同名 doc_id / 同名 raw 文件
    allow_overwrite: bool = False


class ImportConfirmResponse(BaseModel):
    import_id: str
    doc_id: str
    filename: str
    text_len: int
    paragraph_count: int
    message: str


class CorpusOverview(BaseModel):
    docs: int
    active_docs: int
    families: int
    multi_version_families: int
    chunks: int
    text_chars: int
    index_size: int | None = None
    index_dim: int | None = None
    index_built_at: str | None = None
    index_build_seconds: float | None = None
    staging_pending: int


class DocItem(BaseModel):
    doc_id: str
    title: str
    family_id: str
    version: str
    status: str
    file_type: str
    effective_date: str
    chars: int
    text_exists: bool
    raw_exists: bool


class ImportRecord(BaseModel):
    import_id: str
    doc_id: str = ""
    source_name: str
    file_size: int
    status: str
    stage: str
    message: str
    user_id: str = ""
    created_at: str
    updated_at: str
