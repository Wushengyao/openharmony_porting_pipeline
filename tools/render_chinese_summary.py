#!/usr/bin/env python3
"""Render Chinese stage and overall summaries for pipeline results."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE_NAMES = {
    "00_scope_classifier": "范围分类",
    "01_repo_baseline_extractor": "仓库与基线提取",
    "02_raw_record_extractor": "原始记录提取",
    "aux_dirty_workspace": "脏工作区分析",
    "aux_binary_asset_auditor": "二进制资产审计",
    "03_statistics_qc": "统计与一致性检查",
    "04_semantic_analyzer": "语义分析",
    "05_case_kb_builder": "案例知识库构建",
    "06_skill_generator": "技能生成",
    "07_final_auditor": "最终审计",
}

STAGE_ORDER = list(STAGE_NAMES)
STATUS_ZH = {
    "passed": "通过",
    "blocked": "阻塞",
    "partial": "部分完成",
    "unknown": "未知",
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def status_zh(value: str | None) -> str:
    return STATUS_ZH.get(value or "unknown", value or "未知")


def stage_name(stage: str) -> str:
    return STAGE_NAMES.get(stage, stage)


def stage_highlights(data: dict[str, Any]) -> list[list[Any]]:
    keys = [
        ("commit_records_count", "提交记录数"),
        ("file_change_records_count", "文件变更记录数"),
        ("binary_asset_records_count", "二进制/预编译资产数"),
        ("dirty_file_records_count", "脏工作区文件记录数"),
        ("repo_count", "仓库数"),
        ("changed_repo_count", "有变更仓库数"),
        ("case_candidate_count", "候选案例数"),
        ("case_count", "案例数"),
        ("blocking_issue_count", "阻塞问题数"),
        ("non_blocking_issue_count", "非阻塞问题数"),
    ]
    rows = [[label, data[key]] for key, label in keys if key in data]
    blocking = data.get("blocking_issues") or []
    non_blocking = data.get("non_blocking_issues") or []
    if "blocking_issue_count" not in data and blocking:
        rows.append(["阻塞问题数", len(blocking)])
    if "non_blocking_issue_count" not in data and non_blocking:
        rows.append(["非阻塞问题数", len(non_blocking)])
    outputs = data.get("output_files_written") or []
    if outputs:
        rows.append(["输出文件数", len(outputs)])
    return rows


def stage_cn_sentence(data: dict[str, Any]) -> str:
    stage = str(data.get("stage") or "")
    status = status_zh(str(data.get("status") or "unknown"))
    if stage == "03_statistics_qc":
        return (
            f"统计与一致性检查已{status}：提交 {data.get('commit_records_count', 0)} 条，"
            f"文件变更 {data.get('file_change_records_count', 0)} 条，"
            f"二进制/预编译资产 {data.get('binary_asset_records_count', 0)} 条，"
            f"脏工作区文件 {data.get('dirty_file_records_count', 0)} 条。"
        )
    if stage == "07_final_auditor":
        return (
            f"最终审计已{status}：阻塞问题 {data.get('blocking_issue_count', len(data.get('blocking_issues') or []))} 个，"
            f"非阻塞问题 {data.get('non_blocking_issue_count', len(data.get('non_blocking_issues') or []))} 个，"
            f"建议为 `{data.get('recommendation', 'unknown')}`。"
        )
    if stage == "05_case_kb_builder" and "case_count" in data:
        return f"案例知识库构建已{status}：生成 {data.get('case_count')} 个证据约束案例。"
    if stage == "04_semantic_analyzer" and "case_candidate_count" in data:
        return f"语义分析已{status}：识别 {data.get('case_candidate_count')} 个候选案例。"
    return f"{stage_name(stage)}阶段已{status}。"


def render_stage(out: Path, stage: str, stage_result: Path | None) -> Path:
    result_path = stage_result or out / "_stage_results" / f"{stage}.json"
    data = read_json(result_path)
    if not data:
        data = {"stage": stage, "status": "unknown", "summary": "stage result missing"}
    stage_id = str(data.get("stage") or stage)
    result_dir = out / "_stage_results"
    result_dir.mkdir(parents=True, exist_ok=True)
    target = result_dir / f"{stage_id}.zh.md"
    rows = stage_highlights(data)
    lines = [
        f"# 阶段结果：{stage_name(stage_id)}",
        "",
        f"- 阶段 ID：`{stage_id}`",
        f"- 状态：**{status_zh(str(data.get('status') or 'unknown'))}**",
        f"- 生成时间：`{datetime.now().astimezone().isoformat(timespec='seconds')}`",
        "",
        "## 中文摘要",
        "",
        stage_cn_sentence(data),
        "",
    ]
    if data.get("summary"):
        lines.extend(["## 原始摘要", "", str(data.get("summary")), ""])
    if rows:
        lines.extend(["## 关键指标", "", markdown_table(["项目", "值"], rows), ""])
    for title, key in [("阻塞问题", "blocking_issues"), ("非阻塞问题", "non_blocking_issues")]:
        values = data.get(key) or []
        if values:
            lines.extend([f"## {title}", ""])
            lines.extend([f"- {item}" for item in values])
            lines.append("")
    outputs = data.get("output_files_written") or []
    if outputs:
        lines.extend(["## 输出文件", ""])
        lines.extend([f"- `{item}`" for item in outputs])
        lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def render_overall(out: Path) -> list[Path]:
    stage_rows: list[list[Any]] = []
    result_dir = out / "_stage_results"
    for stage in STAGE_ORDER:
        data = read_json(result_dir / f"{stage}.json")
        stage_rows.append(
            [
                stage,
                stage_name(stage),
                status_zh(str(data.get("status") or "unknown")),
                str(data.get("summary") or "")[:160],
            ]
        )
        if data:
            render_stage(out, stage, result_dir / f"{stage}.json")

    stats = read_json(out / "02_statistics/statistics_summary.json")
    audit = read_json(result_dir / "07_final_auditor.json")
    operator = read_json(out / "00_config/operator_context.json")
    audit_dir = out / "06_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    stage_target = audit_dir / "stage_results.zh.md"
    overall_target = audit_dir / "pipeline_summary.zh.md"

    stage_target.write_text(
        "\n".join(
            [
                "# 阶段结果总览",
                "",
                f"生成时间：`{datetime.now().astimezone().isoformat(timespec='seconds')}`",
                "",
                markdown_table(["阶段 ID", "阶段名称", "状态", "摘要"], stage_rows),
                "",
            ]
        ),
        encoding="utf-8",
    )

    metric_rows: list[list[Any]] = []
    for key, label in [
        ("repo_count", "仓库数"),
        ("changed_repo_count", "有变更仓库数"),
        ("commit_records_count", "提交记录数"),
        ("file_change_records_count", "文件变更记录数"),
        ("binary_asset_records_count", "二进制/预编译资产数"),
        ("dirty_file_records_count", "脏工作区文件记录数"),
        ("initial_import_commit_count", "初始导入提交数"),
        ("post_import_commit_count", "导入后提交数"),
    ]:
        if key in stats:
            metric_rows.append([label, stats[key]])

    final_status = status_zh(str(audit.get("status") or "unknown"))
    blocking = audit.get("blocking_issue_count", len(audit.get("blocking_issues") or []))
    non_blocking = audit.get("non_blocking_issue_count", len(audit.get("non_blocking_issues") or []))
    mode = operator.get("mode", "unknown")
    prompted = operator.get("prompted", "unknown")
    overall_target.write_text(
        "\n".join(
            [
                "# 流水线总体结果",
                "",
                f"- 输出目录：`{out}`",
                f"- 运行模式：`{mode}`",
                f"- 是否完成用户问答：`{prompted}`",
                f"- 最终审计状态：**{final_status}**",
                f"- 阻塞问题：**{blocking}**",
                f"- 非阻塞问题：**{non_blocking}**",
                f"- 审计建议：`{audit.get('recommendation', 'unknown')}`",
                f"- 生成时间：`{datetime.now().astimezone().isoformat(timespec='seconds')}`",
                "",
                "## 关键统计",
                "",
                markdown_table(["项目", "值"], metric_rows) if metric_rows else "暂无统计结果。",
                "",
                "## 阶段状态",
                "",
                markdown_table(["阶段 ID", "阶段名称", "状态"], [[row[0], row[1], row[2]] for row in stage_rows]),
                "",
                "## 说明",
                "",
                "中文摘要用于快速查看总体与阶段结果；英文/结构化 JSON 结果仍保留为机器可读事实来源。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return [stage_target, overall_target]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--stage")
    parser.add_argument("--stage-result")
    parser.add_argument("--overall", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    paths: list[Path] = []
    if args.stage:
        paths.append(render_stage(out, args.stage, Path(args.stage_result) if args.stage_result else None))
    if args.overall:
        paths.extend(render_overall(out))
    for path in paths:
        print(f"[中文摘要] {path}")


if __name__ == "__main__":
    main()
