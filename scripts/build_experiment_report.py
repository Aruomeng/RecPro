"""Build a non-confirmatory Markdown/CSV/SVG report from frozen metrics."""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
from pathlib import Path
from typing import Any, Sequence

try:
    from scripts.evaluation_runtime import read_json, sha256_file, write_json_exclusive
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from evaluation_runtime import read_json, sha256_file, write_json_exclusive


def _bar_svg(rows: list[tuple[str, float]], title: str) -> str:
    width, height = 920, 80 + len(rows) * 34
    bars: list[str] = []
    for index, (label, value) in enumerate(rows):
        y = 54 + index * 34
        bar_width = max(1, round(value * 600))
        bars.append(f'<text x="16" y="{y + 15}" font-size="13" fill="#0f172a">{html.escape(label)}</text>')
        bars.append(f'<rect x="190" y="{y}" width="{bar_width}" height="20" rx="4" fill="#2563eb"/>')
        bars.append(f'<text x="{200 + bar_width}" y="{y + 15}" font-size="12" fill="#475569">{value:.4f}</text>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#ffffff"/><text x="16" y="28" font-size="18" font-weight="700" fill="#0f172a">{html.escape(title)}</text>{"".join(bars)}</svg>\n'


def build(run_dir: Path, *, write: bool) -> dict[str, Any]:
    metrics_path = run_dir / "metrics.json"
    metrics = read_json(metrics_path)
    if metrics.get("classification") != "DEVELOPMENT_PROXY" or metrics.get("confirmation_eligible") is not False:
        raise ValueError("report classification must remain DEVELOPMENT_PROXY")
    rows = sorted(metrics["metrics"].items())
    header = ["system_id", "ndcg_at_10", "recall_at_10", "mrr", "coverage", "diversity", "strategy_macro_f1", "trace_completeness"]
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(header)
    for system_id, values in rows:
        writer.writerow([system_id, values["ndcg_at_10"], values["recall_at_10"], values["mrr"], values["resource_coverage"], values["intra_list_topic_diversity"], values["delivery_strategy_macro_f1"], values["trace_completeness"]])
    table_lines = ["| 系统 | NDCG@10 | Recall@10 | MRR | 覆盖率 | 多样性 | 策略 Macro-F1 | Trace 完整率 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for system_id, values in rows:
        table_lines.append(f"| {system_id} | {values['ndcg_at_10']:.4f} | {values['recall_at_10']:.4f} | {values['mrr']:.4f} | {values['resource_coverage']:.4f} | {values['intra_list_topic_diversity']:.4f} | {values['delivery_strategy_macro_f1']:.4f} | {values['trace_completeness']:.4f} |")
    report = "\n".join([
        "# LibraMAS 开发性代理实验报告", "", "> **DEVELOPMENT_PROXY：本报告只验证运行器正确性与机制差异，不能作为真实推荐准确率提升的论文结论。**", "",
        f"- Run ID：`{metrics['run_id']}`", f"- Predictions SHA-256：`{metrics['prediction_sha256']}`", "- DeepSeek 请求：0", "- 数据库写入：0", "", "## 指标", "", *table_lines, "",
        "## 公平性门禁", "", f"- B2 与 Proposed 候选及分数一致：`{metrics['fairness_checks']['B2_vs_Proposed']['same_candidates_and_scores']}`", f"- B3 与 Proposed 候选及分数一致：`{metrics['fairness_checks']['B3_vs_Proposed']['same_candidates_and_scores']}`", f"- B3/Proposed 故障工具与超时一致：`{metrics['fault_matrix']['fair_tool_contract']}`", "",
        "## 故障矩阵", "", f"- 记录数：{metrics['fault_matrix']['rows']}", f"- 降级成功率：{metrics['fault_matrix']['degradation_success_rate']}", f"- Trace 完整率：{metrics['fault_matrix']['trace_completeness']}", "",
        "## 解释边界", "", metrics["interpretation_limit"], "",
    ])
    result = {"schema_version": "experiment-report-manifest-v1", "classification": "DEVELOPMENT_PROXY", "run_id": metrics["run_id"], "metrics_sha256": sha256_file(metrics_path), "outputs": ["report.md", "metrics-table.csv", "ndcg-at-10.svg"], "database_writes": 0, "deepseek_requests": 0, "deletions": 0}
    if write:
        with (run_dir / "report.md").open("x", encoding="utf-8") as handle: handle.write(report)
        with (run_dir / "metrics-table.csv").open("x", encoding="utf-8", newline="") as handle: handle.write(csv_buffer.getvalue())
        with (run_dir / "ndcg-at-10.svg").open("x", encoding="utf-8") as handle: handle.write(_bar_svg([(system_id, float(values["ndcg_at_10"])) for system_id, values in rows], "NDCG@10 · DEVELOPMENT_PROXY"))
        write_json_exclusive(run_dir / "report-manifest.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build(args.run_dir.resolve(), write=args.write)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"[FAIL] experiment report was not built: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
