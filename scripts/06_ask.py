"""06_ask.py — 命令行问答原型（阶段二：调用 pipeline，保持命令行行为不变）

用法：
    python scripts/06_ask.py --question "考试不及格可以补考吗"    # 单次问答
    python scripts/06_ask.py                                      # 交互模式
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import argparse

import config  # noqa: E402
from src.generator import Generator  # noqa: E402
from src.pipeline import QAPipeline  # noqa: E402

LINE = "─" * 44


def _short_heading(hp: str) -> str:
    """去掉 heading_path 里的文档标题前缀，只保留章节路径。"""
    if " > " in hp:
        return hp.split(" > ", 1)[1]
    return hp


def _stage_label(judge: dict) -> str:
    if judge["answerable"]:
        return "可回答(LLM)" if judge["stage"] == "llm" else "可回答(跳过LLM)"
    if judge["stage"] == "threshold":
        return "不可回答（阈值初筛）"
    if judge["stage"] == "llm":
        return "不可回答（LLM二次判定）"
    return "不可回答（无检索结果）"


def ask_once(question, pipeline, show_context) -> dict:
    """单次问答：调用 pipeline.ask()，按命令行格式打印。"""
    r = pipeline.ask(question)
    hits = r["retrieved"]
    top1_score = hits[0]["score"] if hits else 0.0

    print(f"【检索】{len(hits)} 块 | top1={top1_score:.4f}")
    for it in hits[:3]:
        print(f"  [{it['idx']}] {it['chunk_id']}  {it['score']:.4f}  {_short_heading(it['heading_path'])}")

    print(f"【判定】{_stage_label(r['judge'])}")

    print(f"【回答】")
    print(r["answer"])
    if r["refused"]:
        print("（不调用生成模型，判定耗时即全部耗时）")

    if not r["refused"]:
        print(f"【引用来源】")
        for s in r["sources"][:3]:
            print(f"  [{s['idx']}] {s['heading_path']}")
            print(f"      （原文位置：char {s['char_start']}-{s['char_end']}）")

    t = r["timing"]
    print(f"【耗时】检索 {t['retrieve']:.2f}s | 判定 {t['judge']:.2f}s | 生成 {t['generate']:.2f}s | 合计 {t['total']:.2f}s")
    print(LINE)

    return {"answerable": not r["refused"], "stage": r["judge"]["stage"], "total": t["total"],
            "t_retrieve": t["retrieve"], "t_judge": t["judge"], "t_generate": t["generate"]}


def main():
    parser = argparse.ArgumentParser(description="命令行问答原型")
    parser.add_argument("--model", type=str, default=config.OLLAMA_MODEL)
    parser.add_argument("--top-k", type=int, default=config.TOP_K_FINAL)
    parser.add_argument("--strategy", type=str, default="recursive")
    parser.add_argument("--no-llm-check", action="store_true", help="关闭 LLM 二次判定（调试用）")
    parser.add_argument("--show-context", action="store_true", help="打印完整上下文（调试用）")
    parser.add_argument("--question", type=str, default=None, help="单次问答模式")
    args = parser.parse_args()

    generator = Generator(model=args.model) if args.model != config.OLLAMA_MODEL else None
    pipeline = QAPipeline(strategy=args.strategy, top_k=args.top_k,
                          use_llm_check=not args.no_llm_check, generator=generator)

    if args.question:
        print(LINE)
        print(f"问题：{args.question}")
        print()
        ask_once(args.question, pipeline, args.show_context)
        return

    # 交互模式
    print("=" * 44)
    print(" 校园领域智能问答系统（命令行原型）")
    print(f" 模型: {args.model}   检索: 稠密(FAISS)   top_k={args.top_k}")
    print(" 输入问题开始问答；输入 :q 退出")
    print("=" * 44)

    show_context = args.show_context
    stats = {"n": 0, "answerable": 0, "refused": 0, "total_time": 0.0}
    while True:
        try:
            q = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            q = ":q"
        if q == ":q":
            break
        if not q:
            continue
        print(LINE)
        print(f"问题：{q}")
        print()
        result = ask_once(q, pipeline, show_context)
        stats["n"] += 1
        stats["answerable"] += int(result["answerable"])
        stats["refused"] += int(not result["answerable"])
        stats["total_time"] += result["total"]

    avg = stats["total_time"] / stats["n"] if stats["n"] else 0.0
    print(f"\n共问答 {stats['n']} 次 | 可回答 {stats['answerable']} 次 | "
          f"拒答 {stats['refused']} 次 | 平均耗时 {avg:.2f}s")


if __name__ == "__main__":
    main()
