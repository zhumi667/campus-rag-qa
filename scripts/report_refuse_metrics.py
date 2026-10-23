"""report_refuse_metrics.py — 从 eval/data/eval_runs.csv 复算拒答二分类指标

★ 纯计算：只读 CSV + 算指标，不加载嵌入模型、不调用 Ollama（应在 1 秒内完成）。

口径：把「拒答」视为正类。
    tp = 应拒答且拒答（正确拒答）    fp = 可答却拒答（过度拒答）
    fn = 应拒答却未拒答（该拒不拒）  tn = 可答且未拒答（正确放行）

用法：python scripts/report_refuse_metrics.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 项目根入 path

import config  # noqa: E402
from src import eval_metrics  # noqa: E402


def _latest_runs(rows: list) -> list:
    """每个 system 取最后一次 run_id 的记录。"""
    out = []
    for name in sorted({r["system"] for r in rows}):
        sub = [r for r in rows if r["system"] == name]
        last = sub[-1]["run_id"]
        out.append((name, last, [r for r in sub if r["run_id"] == last]))
    return out


def main():
    rows = list(csv.DictReader(open(config.EVAL_RUNS_CSV, encoding="utf-8-sig")))
    n_err = sum(1 for r in rows if r["error"])
    rows = [r for r in rows if not r["error"]]
    print(f"读取 {config.EVAL_RUNS_CSV}")
    print(f"有效记录 {len(rows)} 行（剔除执行失败 {n_err} 行）")

    runs = _latest_runs(rows)

    print("\n" + "=" * 104)
    print("拒答指标复算（口径：拒答=正类）")
    print("=" * 104)
    hdr = (f"{'system':<11}{'n':>4}{'应拒':>5}{'可答':>5}"
           f"{'tp':>4}{'fp':>4}{'fn':>4}{'tn':>4}"
           f"{'P':>8}{'R':>8}{'F1':>8}{'应拒侧拒答率':>14}{'可答侧放行率':>14}{'总体正确率*':>13}")
    print(hdr)
    print("-" * 104)
    metrics = {}
    for name, run_id, sub in runs:
        m = eval_metrics.refuse_binary_metrics(
            [{"refused": r["refused"], "answerable": r["answerable_gt"]} for r in sub])
        metrics[name] = m
        print(f"{name:<11}{m['n']:>4}{m['n_unanswerable']:>5}{m['n_answerable']:>5}"
              f"{m['tp']:>4}{m['fp']:>4}{m['fn']:>4}{m['tn']:>4}"
              f"{m['precision']:>8.3f}{m['recall']:>8.3f}{m['f1']:>8.3f}"
              f"{m['refuse_rate_on_unanswerable']:>14.3f}"
              f"{m['pass_rate_on_answerable']:>14.3f}"
              f"{m['overall_accuracy']:>13.3f}")
    print("-" * 104)
    print("* 参考值：本数据集应拒答题仅占 4/61（6.6%），总体正确率受类别不平衡影响大，不可单独用于比较")

    # 旧口径 vs 新口径
    print("\n【旧口径 vs 新口径：结论差异】")
    print(f"{'system':<11}{'旧口径=总体正确率':>20}{'新口径R(拒答查全率)':>22}{'新口径P(查准率)':>20}{'可答侧放行率':>15}")
    print("-" * 104)
    for name in metrics:
        m = metrics[name]
        print(f"{name:<11}{m['overall_accuracy']:>20.3f}{m['recall']:>22.3f}"
              f"{m['precision']:>20.3f}{m['pass_rate_on_answerable']:>15.3f}")
    print("\n说明：旧口径下 B1/B2(0.934) 看似优于 B3(约 0.75)，但新口径显示")
    print("      B1/B2 的拒答查全率为 0（应对 4 道无依据问题时全部未拒答），")
    print("      该结论由类别不平衡（57 可答 : 4 应拒答）导致，旧口径不可用于比较。")

    # 拒答题逐题明细
    print("\n【4 道应拒答题逐题结果】")
    print(f"{'qid':<7}{'question':<28}" + "".join(f"{n:>12}" for n in metrics))
    print("-" * 84)
    base = [r for r in rows if r["system"] == runs[0][0] and r["category"] == "refuse"]
    for r0 in base:
        cells = []
        for name, _, sub in runs:
            m = [r for r in sub if r["qid"] == r0["qid"]]
            if not m:
                cells.append(f"{'—':>12}")
            else:
                cells.append(f"{('拒答(tp)' if m[0]['refused'] == 'true' else '未拒答(fn)'):>12}")
        print(f"{r0['qid']:<7}{r0['question'][:26]:<28}" + "".join(cells))


if __name__ == "__main__":
    main()
