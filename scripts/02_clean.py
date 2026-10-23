"""02_clean.py — 清洗 data/text/ 下的文本

用法：
    D:\\Miniconda3\\envs\\campus-rag\\python.exe scripts/02_clean.py --dry-run
    D:\\Miniconda3\\envs\\campus-rag\\python.exe scripts/02_clean.py

功能：
    1. 备份 data/text/*.txt -> data/text_raw_backup/（保留原件，同名不覆盖）
    2. 调用 utils.clean_text() 清洗
    3. 章节标题规范化为 # / ## / ###
    4. 打印清洗前后字数对比
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import argparse
import re
import shutil

import config  # noqa: E402
from src import utils  # noqa: E402

logger = utils.get_logger("02_clean")

_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百千零]+章")
_SECTION_RE = re.compile(r"^第[一二三四五六七八九十百千零]+节")
_ARTICLE_RE = re.compile(r"^第[一二三四五六七八九十百千零]+条")


def _has_section(text: str) -> bool:
    """判断文档是否存在「第X节」，用于决定「第X条」的层级"""
    return any(_SECTION_RE.match(line.strip()) for line in text.split("\n"))


def normalize_headings(text: str) -> str:
    """章节标题规范化为 # / ## / ### 层级

    - 第X章 -> #
    - 第X节 -> ##
    - 第X条 -> 有「节」时 ###，无「节」时 ##
    """
    has_section = _has_section(text)
    lines = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if _CHAPTER_RE.match(s):
            lines.append(f"# {s}")
        elif _SECTION_RE.match(s):
            lines.append(f"## {s}")
        elif _ARTICLE_RE.match(s):
            lines.append(f"{'###' if has_section else '##'} {s}")
        else:
            lines.append(s)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="清洗 data/text/ 下的文本")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写文件")
    args = parser.parse_args()

    files = sorted(config.TEXT_DIR.glob("*.txt"))
    if not files:
        print(f"{config.TEXT_DIR} 下没有 txt 文件")
        return

    mode = "dry-run(只统计不写)" if args.dry_run else "写入(先备份)"
    print("=" * 72)
    print(f"待清洗: {len(files)} 份  模式: {mode}")
    print("=" * 72)

    for f in files:
        raw = f.read_text(encoding="utf-8")
        cleaned = normalize_headings(utils.clean_text(raw))

        cn_before = utils.count_chinese(raw)
        cn_after = utils.count_chinese(cleaned)
        n_before = len([l for l in raw.split("\n") if l.strip()])
        n_after = len([l for l in cleaned.split("\n") if l.strip()])

        if not args.dry_run:
            config.TEXT_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            backup_path = config.TEXT_BACKUP_DIR / f.name
            if not backup_path.exists():  # 保留最早原件，不覆盖
                shutil.copy2(f, backup_path)
            f.write_text(cleaned, encoding="utf-8")

        print(f"[{'DRY' if args.dry_run else 'OK'}]  {f.name}")
        print(f"       字数 {cn_before} -> {cn_after}  非空行 {n_before} -> {n_after}")

    print("=" * 72)
    if args.dry_run:
        print("dry-run：未写入任何文件")
    else:
        print(f"清洗完成，原文已备份到 {config.TEXT_BACKUP_DIR}")
    print("=" * 72)


if __name__ == "__main__":
    main()
