"""03_register.py — 生成并校验文档元数据表 data/meta/documents.csv

用法：
    D:\\Miniconda3\\envs\\campus-rag\\python.exe scripts/03_register.py --write   # 写入/更新 CSV
    D:\\Miniconda3\\envs\\campus-rag\\python.exe scripts/03_register.py --verify  # 只校验已存在的 CSV（默认）
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import argparse
import csv
import re

import config  # noqa: E402
from src import utils  # noqa: E402

logger = utils.get_logger("03_register")

# CSV 字段（14 列，顺序严格）
FIELDS = [
    "doc_id", "title", "family_id", "version", "issuer",
    "publish_date", "effective_date", "expire_date", "source_url",
    "file_type", "status", "raw_path", "text_path", "notes",
]

# 必填字段（校验规则 a）
REQUIRED_FIELDS = ["doc_id", "title", "family_id", "version",
                   "file_type", "status", "raw_path", "text_path"]

# 各校验项说明（用于汇总）
CHECK_LABELS = {
    "a": "必填字段非空",
    "b": "doc_id 合法且唯一",
    "c": "同 family_id 的 version 不重复",
    "d": "同 family_id 仅一个 active",
    "e": "text_path 文件存在",
    "f": "effective_date 格式 YYYY-MM-DD",
    "g": "publish_date <= effective_date",
}

# 预置元数据（照抄，不要改动；留空字段保持空字符串）
METADATA_ROWS = [
    {
        "doc_id": "pyfa_ruanjian_2025",
        "title": "2025级软件工程专业培养方案",
        "family_id": "pyfa_ruanjian",
        "version": "2025",
        "issuer": "桂林电子科技大学",
        "publish_date": "2025-09-01",
        "effective_date": "2025-09-01",
        "expire_date": "",
        "source_url": "",
        "file_type": "pdf",
        "status": "active",
        "raw_path": "data/raw/2025级软件工程专业培养方案(主修).pdf",
        "text_path": "data/text/pyfa_ruanjian_2025.txt",
        "notes": "2025级主修培养方案；结构为“一、专业简介/二、培养目标/三、课程设置”，无“第X章”层级",
    },
    {
        "doc_id": "pyfa_jisuanji_2025",
        "title": "2025级计算机科学与技术专业培养方案",
        "family_id": "pyfa_jisuanji",
        "version": "2025",
        "issuer": "桂林电子科技大学",
        "publish_date": "2025-09-01",
        "effective_date": "2025-09-01",
        "expire_date": "",
        "source_url": "",
        "file_type": "pdf",
        "status": "active",
        "raw_path": "data/raw/2025级计算机科学与技术专业培养方案(主修).pdf",
        "text_path": "data/text/pyfa_jisuanji_2025.txt",
        "notes": "2025级主修培养方案；与本课题专业同属计算机类",
    },
    {
        "doc_id": "pyfa_zidonghua_2025",
        "title": "2025级自动化专业培养方案",
        "family_id": "pyfa_zidonghua",
        "version": "2025",
        "issuer": "桂林电子科技大学",
        "publish_date": "2025-09-01",
        "effective_date": "2025-09-01",
        "expire_date": "",
        "source_url": "",
        "file_type": "pdf",
        "status": "active",
        "raw_path": "data/raw/2025级自动化专业培养方案(主修) .pdf",
        "text_path": "data/text/pyfa_zidonghua_2025.txt",
        "notes": "2025级主修培养方案；注意源文件名尾部有空格",
    },
    {
        "doc_id": "pyfa_dianqi_2025",
        "title": "2025级电气工程及其自动化专业培养方案",
        "family_id": "pyfa_dianqi",
        "version": "2025",
        "issuer": "桂林电子科技大学",
        "publish_date": "2025-09-01",
        "effective_date": "2025-09-01",
        "expire_date": "",
        "source_url": "",
        "file_type": "pdf",
        "status": "active",
        "raw_path": "data/raw/2025级电气工程及其自动化专业培养方案(主修).pdf",
        "text_path": "data/text/pyfa_dianqi_2025.txt",
        "notes": "2025级主修培养方案",
    },
    {
        "doc_id": "pyfa_rengongzhineng_2025",
        "title": "2025级人工智能专业培养方案",
        "family_id": "pyfa_rengongzhineng",
        "version": "2025",
        "issuer": "桂林电子科技大学",
        "publish_date": "2025-09-01",
        "effective_date": "2025-09-01",
        "expire_date": "",
        "source_url": "",
        "file_type": "pdf",
        "status": "active",
        "raw_path": "data/raw/2025级人工智能专业培养方案(主修).pdf",
        "text_path": "data/text/pyfa_rengongzhineng_2025.txt",
        "notes": "2025级主修培养方案",
    },
    {
        "doc_id": "xjgl_2025",
        "title": "桂林电子科技大学普通高等教育本科学生学籍管理规定（2025年修订）",
        "family_id": "xjgl",
        "version": "2025",
        "issuer": "桂林电子科技大学",
        "publish_date": "2025-07-24",
        "effective_date": "2025-07-24",
        "expire_date": "",
        "source_url": "",
        "file_type": "pdf",
        "status": "active",
        "raw_path": "data/raw/桂电教〔2025〕27号--关于印发《桂林电子科技大学普通高等教育本科学生学籍管理规定（2025年修订）》的通知.pdf",
        "text_path": "data/text/xjgl_2025.txt",
        "notes": "桂电教〔2025〕27号；13章54条；含毕业/结业/学位授予条件",
    },
    {
        "doc_id": "kshgl_2020",
        "title": "桂林电子科技大学考试管理规定",
        "family_id": "kshgl",
        "version": "2020",
        "issuer": "桂林电子科技大学",
        "publish_date": "2020-06-28",
        "effective_date": "2020-06-28",
        "expire_date": "",
        "source_url": "",
        "file_type": "pdf",
        "status": "active",
        "raw_path": "data/raw/桂电教〔2020〕15号关于印发《桂林电子科技大学考试管理规定》的通知.pdf",
        "text_path": "data/text/kshgl_2020.txt",
        "notes": "桂电教〔2020〕15号；10章30条；含考试违规认定与处理程序",
    },
    {
        "doc_id": "zzy_2021",
        "title": "桂林电子科技大学本科生专业分流及转专业管理办法（修订）",
        "family_id": "zzy",
        "version": "2021",
        "issuer": "桂林电子科技大学",
        "publish_date": "2021-01-22",
        "effective_date": "2021-01-22",
        "expire_date": "",
        "source_url": "",
        "file_type": "pdf",
        "status": "active",
        "raw_path": "data/raw/桂电教〔2021〕6号--关于印发《桂林电子科技大学本科生专业分流及转专业管理办法（修订）》的通知.pdf",
        "text_path": "data/text/zzy_2021.txt",
        "notes": "桂电教〔2021〕6号；5章21条",
    },
    {
        "doc_id": "sysaq_2021",
        "title": "桂林电子科技大学实验室安全管理办法（试行）",
        "family_id": "sysaq",
        "version": "2021",
        "issuer": "桂林电子科技大学",
        "publish_date": "2021-07-26",
        "effective_date": "2021-07-26",
        "expire_date": "",
        "source_url": "",
        "file_type": "pdf",
        "status": "active",
        "raw_path": "data/raw/syjaq_2021.pdf",
        "text_path": "data/text/sysaq_2021.txt",
        "notes": "桂电教〔2021〕30号；7章28条；试行",
    },
    {
        "doc_id": "gjjxj_2026",
        "title": "关于开展2025-2026学年度国家奖学金评审推荐工作的通知",
        "family_id": "gjjxj",
        "version": "2026",
        "issuer": "桂林电子科技大学",
        "publish_date": "",
        "effective_date": "",
        "expire_date": "",
        "source_url": "",
        "file_type": "docx",
        "status": "active",
        "raw_path": "data/raw/gjjxj_2026.docx",
        "text_path": "data/text/gjjxj_2026.txt",
        "notes": "含奖励标准（10000元/年）与排名前10%等申请条件；publish_date待人工确认",
    },
    {
        "doc_id": "wangluo_jieshao",
        "title": "网络工程专业介绍（应用型本科）",
        "family_id": "wangluo_jieshao",
        "version": "2025",
        "issuer": "桂林电子科技大学北海校区",
        "publish_date": "",
        "effective_date": "",
        "expire_date": "",
        "source_url": "",
        "file_type": "pdf",
        "status": "active",
        "raw_path": "data/raw/网络工程（应本）-招生信息网.pdf",
        "text_path": "data/text/wangluo_jieshao.txt",
        "notes": "招生信息网专业介绍；含最低毕业学分166、核心课程、授工学学士；publish_date待人工确认",
    },
    {
        "doc_id": "qzcybt_2023",
        "title": "广西高校毕业生求职创业补贴系统操作手册（2023版）",
        "family_id": "qzcybt",
        "version": "2023",
        "issuer": "广西壮族自治区人力资源和社会保障厅",
        "publish_date": "2023-09-01",
        "effective_date": "",
        "expire_date": "",
        "source_url": "",
        "file_type": "docx",
        "status": "active",
        "raw_path": "data/raw/附件4：求职创业补贴系统操作手册（2023版-参考）.docx",
        "text_path": "data/text/qzcybt_2023.txt",
        "notes": "办事流程类",
    },
    {
        "doc_id": "tzjk_2026",
        "title": "关于开展2026年10月学生体质健康测试工作的通知",
        "family_id": "tzjk",
        "version": "2026",
        "issuer": "桂林电子科技大学北海校区",
        "publish_date": "2026-09-15",
        "effective_date": "",
        "expire_date": "",
        "source_url": "",
        "file_type": "docx",
        "status": "active",
        "raw_path": "data/raw/关于开展2026年10月学生体质健康测试工作的通知.docx",
        "text_path": "data/text/tzjk_2026.txt",
        "notes": "通知类；含测试时间地点与注意事项",
    },
    {
        "doc_id": "dfcfb_2026",
        "title": "2026年“东方财富杯”全国大学生金融安全知识网络比拼活动参赛说明",
        "family_id": "dfcfb",
        "version": "2026",
        "issuer": "",
        "publish_date": "",
        "effective_date": "",
        "expire_date": "",
        "source_url": "",
        "file_type": "docx",
        "status": "active",
        "raw_path": "data/raw/通知1：2026年“东方财富杯”全国大学生金融安全知识网络比拼活动参赛说明.docx",
        "text_path": "data/text/dfcfb_2026.txt",
        "notes": "活动通知类；issuer与publish_date待人工确认",
    },
]


def _write_csv(path: Path, rows: list) -> None:
    """用 utf-8-sig 编码写入 CSV（方便 Excel 打开）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})


def _read_csv(path: Path) -> list:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _merge_rows(existing: list, preset: list) -> tuple:
    """把预置行合并进已存在的表：按 doc_id 更新/追加，**不删除**其他行。

    ★ 为什么需要这个（而不是直接覆盖）：
      管理员通过「语料导入」功能添加的文档，其元数据不在 METADATA_ROWS 里。
      若 --write 直接整表覆盖，这些记录会被静默删除 —— 表现为"导入过的文档
      突然从语料中消失"，且 documents.csv 与 data/text/ 不再一致。
      因此默认采用合并语义；确需回到初始 14 行时用 --reset。

    返回 (合并后的行列表, 新增数, 更新数)
    """
    by_id = {r.get("doc_id"): dict(r) for r in existing}
    added = updated = 0
    for row in preset:
        did = row.get("doc_id")
        if did in by_id:
            if by_id[did] != row:
                updated += 1
            by_id[did] = dict(row)
        else:
            by_id[did] = dict(row)
            added += 1
    # 保持顺序：预置行在前（按 METADATA_ROWS 顺序），其余行按原顺序追加在后
    ordered, seen = [], set()
    for row in preset:
        did = row.get("doc_id")
        if did in by_id and did not in seen:
            ordered.append(by_id[did])
            seen.add(did)
    for r in existing:
        did = r.get("doc_id")
        if did not in seen and did in by_id:
            ordered.append(by_id[did])
            seen.add(did)
    return ordered, added, updated


def _verify_rows(rows: list) -> dict:
    """逐行校验，返回 {校验项: [问题列表]}"""
    problems = {k: [] for k in CHECK_LABELS}
    seen_doc_ids = {}
    family_versions = {}
    family_active = {}

    for i, row in enumerate(rows, start=2):  # 第 1 行是表头，数据从第 2 行起
        doc_id = row.get("doc_id", "").strip()
        family_id = row.get("family_id", "").strip()
        version = row.get("version", "").strip()
        status = row.get("status", "").strip()

        # a. 必填字段非空
        for field in REQUIRED_FIELDS:
            if not row.get(field, "").strip():
                problems["a"].append(f"行{i}: 必填字段 {field} 为空")

        # b. doc_id 唯一、只含小写字母/数字/下划线
        if doc_id:
            if not re.fullmatch(r"[a-z0-9_]+", doc_id):
                problems["b"].append(f"行{i}: doc_id={doc_id!r} 含非法字符（仅允许小写字母/数字/下划线）")
            if doc_id in seen_doc_ids:
                problems["b"].append(f"行{i}: doc_id={doc_id!r} 重复（首次出现在第{seen_doc_ids[doc_id]}行）")
            else:
                seen_doc_ids[doc_id] = i

        # c. family_id 相同的行，version 必须不同
        if family_id and version:
            family_versions.setdefault(family_id, set())
            if version in family_versions[family_id]:
                problems["c"].append(f"行{i}: family_id={family_id!r} 下 version={version!r} 重复")
            family_versions[family_id].add(version)

        # d. 同一 family_id 内只能有一行 status=active
        if family_id and status == "active":
            family_active[family_id] = family_active.get(family_id, 0) + 1
            if family_active[family_id] > 1:
                problems["d"].append(f"行{i}: family_id={family_id!r} 存在多个 status=active")

        # e. text_path 指向的文件必须真实存在
        text_path = row.get("text_path", "").strip()
        if text_path:
            if not (config.BASE_DIR / text_path).exists():
                problems["e"].append(f"行{i}: text_path 不存在: {text_path}")

        # f. effective_date 若不为空，格式必须是 YYYY-MM-DD
        eff = row.get("effective_date", "").strip()
        if eff and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", eff):
            problems["f"].append(f"行{i}: effective_date={eff!r} 格式非 YYYY-MM-DD")

        # g. publish_date <= effective_date（两者都非空时）
        pub = row.get("publish_date", "").strip()
        if pub and eff:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", pub) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", eff):
                if pub > eff:
                    problems["g"].append(f"行{i}: publish_date={pub} > effective_date={eff}")

    return problems


def _print_summary(rows: list, problems: dict) -> None:
    total_problems = sum(len(v) for v in problems.values())
    print("=" * 72)
    print(f"校验汇总：总行数 {len(rows)}")
    for key, label in CHECK_LABELS.items():
        status = "通过" if not problems[key] else f"{len(problems[key])} 个问题"
        print(f"  校验{key}（{label}）: {status}")
    print(f"问题总数: {total_problems}")
    if total_problems:
        print("问题清单:")
        for key, label in CHECK_LABELS.items():
            for p in problems[key]:
                print(f"  [{key}] {p}")
    else:
        print("所有校验项通过")
    print("=" * 72)


def main():
    parser = argparse.ArgumentParser(description="生成并校验文档元数据表")
    parser.add_argument("--write", action="store_true",
                        help="写入/更新 CSV（★ 合并语义：按 doc_id 更新或追加，不删除其他行）")
    parser.add_argument("--reset", action="store_true",
                        help="★ 危险：丢弃 CSV 中不在 METADATA_ROWS 里的行，恢复为初始 14 行")
    parser.add_argument("--verify", action="store_true", help="只校验已存在的 CSV（默认行为）")
    args = parser.parse_args()

    meta_csv = config.META_CSV

    if args.reset:
        if meta_csv.exists():
            kept = {r.get("doc_id") for r in _read_csv(meta_csv)}
            drop = kept - {r.get("doc_id") for r in METADATA_ROWS}
            if drop:
                print(f"⚠️ --reset 将删除 {len(drop)} 行：{sorted(drop)}")
        _write_csv(meta_csv, METADATA_ROWS)
        print(f"已重置元数据表: {meta_csv}（共 {len(METADATA_ROWS)} 行）")
        rows = _read_csv(meta_csv)
        _print_summary(rows, _verify_rows(rows))
        return

    if args.write or not meta_csv.exists():
        if meta_csv.exists():
            existing = _read_csv(meta_csv)
            merged, added, updated = _merge_rows(existing, METADATA_ROWS)
            _write_csv(meta_csv, merged)
            print(f"已更新元数据表: {meta_csv}")
            print(f"  预置行 {len(METADATA_ROWS)} 条（新增 {added}，更新 {updated}）"
                  f"，保留其他 {len(merged) - len(METADATA_ROWS)} 条")
        else:
            _write_csv(meta_csv, METADATA_ROWS)
            print(f"已写入元数据表: {meta_csv}（共 {len(METADATA_ROWS)} 行）")
        rows = _read_csv(meta_csv)
        _print_summary(rows, _verify_rows(rows))
    elif args.verify:
        if not meta_csv.exists():
            print(f"CSV 不存在: {meta_csv}，请先运行 --write")
            return
        rows = _read_csv(meta_csv)
        _print_summary(rows, _verify_rows(rows))
    else:
        # 默认：校验已存在的 CSV
        rows = _read_csv(meta_csv)
        _print_summary(rows, _verify_rows(rows))


if __name__ == "__main__":
    main()
