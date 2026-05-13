#!/usr/bin/env python3
"""Collect optional human collaboration context for the porting pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO


QUESTIONS = [
    {
        "id": "project_background",
        "stage_hint": "00_scope_classifier",
        "question": "当前项目的背景是什么？例如目标产品、板卡、SoC、客户/业务场景、移植目标。不了解可直接回车。",
    },
    {
        "id": "target_runtime_scope",
        "stage_hint": "00_scope_classifier",
        "question": "OpenHarmony 运行在哪个主架构/核心上？是否存在辅助核、固件、DSP、RISC-V 等异构部分？不了解可直接回车。",
    },
    {
        "id": "before_porting_boundary",
        "stage_hint": "01_repo_baseline_extractor",
        "question": "如何确定“移植前”的边界？例如上游 tag、SDK 初始导入点、baseline manifest、分支名或提交号。不了解可直接回车。",
    },
    {
        "id": "after_porting_boundary",
        "stage_hint": "01_repo_baseline_extractor",
        "question": "如何确定“移植后”的边界？例如当前分支、交付 tag、最终验证提交、产品分支。不了解可直接回车。",
    },
    {
        "id": "known_porting_commits",
        "stage_hint": "02_raw_record_extractor",
        "question": "哪些提交、提交范围或目录你认为属于移植工作？哪些明确不是？不了解可直接回车。",
    },
    {
        "id": "dirty_workspace_policy",
        "stage_hint": "aux_dirty_workspace",
        "question": "当前脏工作区/未跟踪文件应如何看待？例如正在开发、构建产物、供应商预置、应排除。不了解可直接回车。",
    },
    {
        "id": "binary_asset_provenance",
        "stage_hint": "aux_binary_asset_auditor",
        "question": "二进制/预编译/固件资产的来源、许可证、可再分发性或生成方式有已知信息吗？不了解可直接回车。",
    },
    {
        "id": "knowledge_priorities",
        "stage_hint": "04_semantic_analyzer,05_case_kb_builder,06_skill_generator",
        "question": "最终知识沉淀更希望关注哪些主题？例如 WiFi、音频、HDF、启动、产品配置、构建系统、驱动、风险审计。不了解可直接回车。",
    },
    {
        "id": "additional_notes",
        "stage_hint": "all",
        "question": "还有其他需要 Codex 注意的事实、假设或禁区吗？不了解可直接回车。",
    },
]

UNKNOWN_VALUES = {"", "unknown", "unk", "n/a", "na", "none", "不知道", "不清楚", "不确定", "无"}


def normalize_answer(value: str) -> tuple[str, str]:
    text = value.strip()
    if text.lower() in UNKNOWN_VALUES:
        return "unknown", "unknown"
    return text, "user"


def open_prompt_streams() -> tuple[TextIO | None, TextIO | None]:
    if sys.stdin.isatty() and sys.stdout.isatty():
        return sys.stdin, sys.stdout
    try:
        return open("/dev/tty", "r", encoding="utf-8"), open("/dev/tty", "w", encoding="utf-8")
    except OSError:
        return None, None


def ask_collaboration_questions() -> tuple[list[dict[str, str]], bool]:
    reader, writer = open_prompt_streams()
    if reader is None or writer is None:
        return [
            {
                "id": item["id"],
                "stage_hint": item["stage_hint"],
                "question": item["question"],
                "answer": "unknown",
                "source": "not_prompted_non_interactive",
            }
            for item in QUESTIONS
        ], False

    answers: list[dict[str, str]] = []
    writer.write("\nOpenHarmony porting pipeline human collaboration mode.\n")
    writer.write("Please answer briefly. Press Enter for unknown.\n\n")
    writer.flush()
    for idx, item in enumerate(QUESTIONS, start=1):
        writer.write(f"[{idx}/{len(QUESTIONS)}] {item['question']}\n> ")
        writer.flush()
        raw = reader.readline()
        answer, source = normalize_answer(raw)
        answers.append(
            {
                "id": item["id"],
                "stage_hint": item["stage_hint"],
                "question": item["question"],
                "answer": answer,
                "source": source,
            }
        )
    writer.write("\nHuman collaboration context captured.\n\n")
    writer.flush()
    return answers, True


def auto_answers() -> list[dict[str, str]]:
    return [
        {
            "id": item["id"],
            "stage_hint": item["stage_hint"],
            "question": item["question"],
            "answer": "unknown",
            "source": "auto_mode_default",
        }
        for item in QUESTIONS
    ]


def yaml_block(value: str, indent: str = "      ") -> str:
    if value == "":
        value = "unknown"
    return "\n".join(f"{indent}{line}" if line else indent for line in value.splitlines())


def write_outputs(out: Path, data: dict[str, object]) -> None:
    config = out / "00_config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "operator_context.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Operator Context",
        "",
        f"- mode: `{data['mode']}`",
        f"- prompted: `{str(data['prompted']).lower()}`",
        f"- generated_at: `{data['generated_at']}`",
        "",
        "These answers are user-supplied hints. They are not repository evidence. If they conflict with manifests, commits, diffs, or raw records, later stages must record the conflict and prefer verifiable evidence.",
        "",
        "## Answers",
        "",
    ]
    for item in data["answers"]:  # type: ignore[index]
        lines.extend(
            [
                f"### {item['id']}",
                "",
                f"- stage_hint: `{item['stage_hint']}`",
                f"- source: `{item['source']}`",
                "",
                item["answer"],
                "",
            ]
        )
    (config / "operator_context.md").write_text("\n".join(lines), encoding="utf-8")

    yaml_lines = [
        f"mode: {data['mode']}",
        f"prompted: {str(data['prompted']).lower()}",
        f"generated_at: {data['generated_at']}",
        "answers:",
    ]
    for item in data["answers"]:  # type: ignore[index]
        yaml_lines.extend(
            [
                f"  {item['id']}:",
                f"    stage_hint: {item['stage_hint']}",
                f"    source: {item['source']}",
                "    answer: |-",
                yaml_block(item["answer"]),
            ]
        )
    (config / "operator_context.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=["auto", "collab", "human", "interactive"], default="auto")
    args = parser.parse_args()

    mode = "collab" if args.mode in {"human", "interactive"} else args.mode
    if mode == "collab":
        answers, prompted = ask_collaboration_questions()
    else:
        answers, prompted = auto_answers(), False
    data = {
        "mode": mode,
        "prompted": prompted,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "answers": answers,
    }
    out = Path(args.out)
    write_outputs(out, data)
    print(json.dumps({"mode": mode, "prompted": prompted, "answers": len(answers)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
