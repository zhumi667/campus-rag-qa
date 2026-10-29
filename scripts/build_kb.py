"""scripts/build_kb.py — 一条命令完成知识库构建（包装脚本）

依次调用既有的 5 个步骤脚本，不复制、不改写它们的逻辑：
    01_parse.py → 02_clean.py → 03_register.py → 04_chunk.py → 05_build_index.py

用法：
    python scripts/build_kb.py                # 全流程
    python scripts/build_kb.py --step chunk   # 只跑某一步
    python scripts/build_kb.py --from index   # 从某一步跑到最后

★ 因为每个步骤都可能耗时数十秒并输出大量日志，这里用 subprocess 逐个调用，
  既保持各脚本可独立运行（便于调试与论文复现），又提供一条命令的入口。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

STEPS = [
    ("parse",    "01_parse.py"),
    ("clean",    "02_clean.py"),
    ("register", "03_register.py"),
    ("chunk",    "04_chunk.py"),
    ("index",    "05_build_index.py"),
]
NAMES = [s[0] for s in STEPS]


def main():
    ap = argparse.ArgumentParser(description="一键构建知识库")
    ap.add_argument("--step", choices=NAMES, help="只执行指定步骤")
    ap.add_argument("--from", dest="from_step", choices=NAMES, help="从指定步骤执行到结束")
    args = ap.parse_args()

    if args.step:
        todo = [s for s in STEPS if s[0] == args.step]
    elif args.from_step:
        todo = STEPS[NAMES.index(args.from_step):]
    else:
        todo = STEPS

    script_dir = Path(__file__).resolve().parent
    total = time.perf_counter()

    for i, (name, filename) in enumerate(todo, 1):
        path = script_dir / filename
        if not path.exists():
            print(f"[{i}/{len(todo)}] 跳过 {name}：找不到 {filename}")
            continue
        print(f"\n{'=' * 60}\n[{i}/{len(todo)}] 执行 {name}  ({filename})\n{'=' * 60}")
        t0 = time.perf_counter()
        proc = subprocess.run([sys.executable, str(path)], cwd=str(script_dir.parent))
        if proc.returncode != 0:
            print(f"\n✗ 步骤 {name} 失败（退出码 {proc.returncode}），已中止")
            return proc.returncode
        print(f"✓ {name} 完成，耗时 {time.perf_counter() - t0:.1f}s")

    print(f"\n全部完成，总耗时 {time.perf_counter() - total:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
