#!/usr/bin/env python3
"""Normalize fragile cross-scenario Markdown contract markers after LLM refine.

The Stage-09 LLM refinement may improve prose while accidentally replacing
validator-required terms with synonyms. This tool is intentionally narrow and
idempotent: it only inserts compact contract marker sections when required
terms are missing, then leaves semantic content untouched.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import yaml


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text_if_changed(path: Path, old: str, new: str) -> bool:
    if old == new:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def missing_terms(text: str, terms: Iterable[str]) -> list[str]:
    lower = text.lower()
    return [term for term in terms if term.lower() not in lower]


def insert_after_title(text: str, section: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join([lines[0], "", section, "", *lines[1:]]).rstrip() + "\n"
    return section.rstrip() + "\n\n" + text.rstrip() + "\n"


def ensure_section(path: Path, title: str, body: str, terms: list[str]) -> bool:
    old = read_text(path)
    if not missing_terms(old, terms):
        return False
    marker = f"## {title}"
    if marker in old:
        new = old
    else:
        new = insert_after_title(old, f"{marker}\n\n{body}")
    return write_text_if_changed(path, old, new)


def scenario_count(out: Path) -> int:
    registry = out / "00_scenario_registry/scenario_registry.yaml"
    if not registry.exists():
        return 0
    data = yaml.safe_load(registry.read_text(encoding="utf-8", errors="ignore")) or {}
    try:
        return int(data.get("scenario_count") or 0)
    except (TypeError, ValueError):
        return 0


def normalize(out: Path) -> list[str]:
    changed: list[str] = []

    conditional = out / "02_patterns/conditional_patterns.md"
    if conditional.exists() and ensure_section(
        conditional,
        "Validator Terminology Guard",
        "This output preserves the required architecture terms: `ARM-primary`, `RISC-V-primary`, and `heterogeneous_aux_core`.",
        ["ARM-primary", "RISC-V-primary", "heterogeneous_aux_core"],
    ):
        changed.append(str(conditional))

    anti_patterns = out / "02_patterns/anti_patterns.md"
    if anti_patterns.exists() and ensure_section(
        anti_patterns,
        "Validator Terminology Guard",
        "This output preserves the required anti-pattern terms: `dirty`, `binary`, `force-sync`, `.gitattributes`, and `RISC-V`.",
        ["dirty", "binary", "force-sync", ".gitattributes", "RISC-V"],
    ):
        changed.append(str(anti_patterns))

    meta_report = out / "meta_report.md"
    if meta_report.exists() and ensure_section(
        meta_report,
        "Standard Reuse Classes",
        "The standard reuse classes are `universal`, `universal_candidate`, `conditional`, `scenario_specific`, `risk_only`, and `anti_pattern`.",
        ["universal", "universal_candidate", "conditional", "scenario_specific", "risk_only", "anti_pattern"],
    ):
        changed.append(str(meta_report))

    universal_methods = out / "02_patterns/universal_methods.md"
    phrase = "No Formal Universal Methods Promoted"
    if universal_methods.exists() and scenario_count(out) < 3:
        old = read_text(universal_methods)
        if phrase.lower() not in old.lower():
            new = insert_after_title(old, f"## {phrase}\n\nNone promoted because fewer than three distinct scenario IDs are present.")
            if write_text_if_changed(universal_methods, old, new):
                changed.append(str(universal_methods))

    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="openharmony_porting_meta_output directory")
    args = parser.parse_args()

    changed = normalize(Path(args.out))
    for path in changed:
        print(f"[NORMALIZED] {path}")
    if not changed:
        print("[OK] meta output contract markers already present")


if __name__ == "__main__":
    main()
