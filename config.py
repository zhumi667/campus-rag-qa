"""config.py — 全局配置中心

本项目所有路径、模型名、参数集中在此文件，业务代码一律从这里导入，禁止硬编码。
"""
from pathlib import Path

# ============================================================
# 项目根目录（本文件所在目录，即 D:\campus-rag）
# ============================================================
BASE_DIR = Path(__file__).resolve().parent

# ============================================================
# 目录路径
# ============================================================
RAW_DIR = BASE_DIR / "data" / "raw"          # 正式语料（不可修改）
RAW_DEV_DIR = BASE_DIR / "data" / "raw_dev"  # 开发调试语料（虚构，test_ 前缀）
TEXT_DIR = BASE_DIR / "data" / "text"        # 解析后的归一化文本（正式语料）
TEXT_DEV_DIR = BASE_DIR / "data" / "text_dev"  # 开发调试语料解析文本（raw_dev 用）
TEXT_BACKUP_DIR = BASE_DIR / "data" / "text_backup"  # 清洗前的文本备份（02_clean 用）
META_DIR = BASE_DIR / "data" / "meta"        # 元数据目录
META_CSV = META_DIR / "documents.csv"        # 元数据登记表
CHUNK_DIR = BASE_DIR / "data" / "chunks"     # 切分结果（正式语料）
CHUNK_DEV_DIR = BASE_DIR / "data" / "chunks_dev"  # 切分结果（开发调试语料）
INDEX_DIR = BASE_DIR / "data" / "index"      # FAISS 索引（正式语料）
INDEX_DEV_DIR = BASE_DIR / "data" / "index_dev"  # FAISS 索引（开发调试语料）

# 会话数据库（SQLite）。放在独立子目录，避免与语料目录混在一起。
# ★ 整个文件可安全删除：后端启动时 db.init_db() 会自动重建表结构与默认用户。
DB_DIR = BASE_DIR / "data" / "db"
DB_PATH = DB_DIR / "app.db"
MODEL_DIR = BASE_DIR / "models"              # 本地模型目录
LOG_DIR = BASE_DIR / "logs"                  # 日志目录

# ============================================================
# 模型
# ============================================================
EMBED_MODEL_PATH = MODEL_DIR / "bge-small-zh-v1.5"  # 嵌入模型（本地，512 维）
EMBED_MODEL_NAME = "bge-small-zh-v1.5"
EMBED_DEVICE = "cuda"       # 嵌入模型运行设备：cuda / cpu
EMBED_DIM = 512             # 嵌入向量维度（BGE-small-zh-v1.5）

RERANK_MODEL_NAME = "bge-reranker-base"      # 重排模型（已下载到本地）
RERANK_MODEL_PATH = MODEL_DIR / "bge-reranker-base"   # 重排模型本地路径（禁止运行时联网下载）
RERANK_ENABLED = False       # 是否启用 Cross-Encoder 重排（阶段三）；默认关闭，不改变既有行为
RERANK_TOP_K = 20            # 送入重排的召回数量
RERANK_BATCH_SIZE = 16       # 重排批大小（显存有限，勿过大）
RERANK_DEVICE = "cuda"       # 重排运行设备：cuda / cpu

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5-3b-q4"               # 正式生成模型
DEBUG_MODEL = "qwen2.5-1.5b-test"            # 调试用小模型

# ============================================================
# 切分参数
# ============================================================
# CHUNK_SIZE/CHUNK_OVERLAP 供固定长度切分使用（阶段三）；
# CHUNK_TARGET_*/CHUNK_HARD_MAX 供递归结构感知切分使用（当前）
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
CHUNK_TARGET_MIN = 400   # 递归切分：目标块最小 token
CHUNK_TARGET_MAX = 600   # 递归切分：目标块最大 token
CHUNK_HARD_MAX = 800     # 递归切分：硬上限，超过则强制切分
SEMANTIC_THRESHOLD_PERCENTILE = 10           # 语义切分：相似度阈值百分位

# ============================================================
# 检索参数
# ============================================================
TOP_K_RECALL = 20     # 粗排召回数量
TOP_K_FINAL = 5       # 最终送入生成的数量
HYBRID_ALPHA = 0.7    # 混合检索中稠密检索权重（0~1）
SCORE_THRESHOLD = 0.45  # 拒答相似度阈值。经验值，阶段三将在评估集上调优。
JUDGE_MAX_CHECK = 3   # 判定器逐块检查的最大块数（阶段三 max_check 消融实验用；默认 3，不改变现有行为）

# ============================================================
# 生成参数
# ============================================================
NUM_CTX = 4096
TEMPERATURE = 0.1
MAX_TOKENS = None     # 单次生成最大 token 数（待测，用模型默认值）

# ============================================================
# 版本与文档状态过滤（检索期生效）
# ============================================================
# ★ 接入说明（2026-10-05）：这两个开关此前只定义、未被任何代码使用；
#   现已在 src/retriever.py 的 _is_retrievable() 中接线。过滤规则：
#     ① status 必须是 active（inactive=已失效 / draft=草稿 均不予引用）
#     ② effective_date 若存在，必须 <= 基准日期（未生效的不能引用）
#     ③ expire_date   若存在，必须 >  基准日期（已过期的不能引用）
#   基准日期取 DEFAULT_AS_OF_DATE，为空时取当天。
VERSION_FILTER_ENABLED = True
DEFAULT_AS_OF_DATE = None     # 形如 "2026-10-05"；None 表示按当天判断

# 状态过滤开启时的检索超取倍数。
# ★ 为什么需要：过滤发生在检索之后，若只召回 top_k 条，被滤掉若干条后
#   实际返回数会少于 top_k（送入生成的资料变少、引用编号也会跳号）。
#   超取 fetch_k = min(top_k × 本值, 200)，再截取前 top_k 条。
RETRIEVE_OVERFETCH = 3

# ============================================================
# 评估
# ============================================================
# eval/ 的目录结构（按文件类型分层，避免 20+ 个文件平铺）：
#   eval/               评测框架代码（runner.py / baselines.py）
#   eval/data/          实验数据（评估集、逐题结果、明细 JSON）
#   eval/reports/       人工评分表（xlsx）
#   eval/*.md           实验记录与规范（与代码同级，便于对照）
EVAL_DIR = BASE_DIR / "eval"
EVAL_DATA_DIR = EVAL_DIR / "data"        # ★ 数据文件统一放这里
EVAL_REPORTS_DIR = EVAL_DIR / "reports"  # ★ 人工评分表

EVAL_RUNS_CSV = EVAL_DATA_DIR / "eval_runs.csv"    # 所有实验结果的唯一数据源
EVAL_QUESTIONS_CSV = EVAL_DATA_DIR / "questions.csv"  # 评估集（85 题，已冻结）

# ============================================================
# 日志文件
# ============================================================
TIMING_FILE = LOG_DIR / "timing.md"
LOG_FILE = LOG_DIR / "app.log"
