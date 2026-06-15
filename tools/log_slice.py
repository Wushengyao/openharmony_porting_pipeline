#!/usr/bin/env python3
"""Slice large OpenHarmony logs into evidence-bound excerpts."""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except Exception:  # pragma: no cover - fallback for minimal hosts
    yaml = None


BUILTIN_SIGNATURES = [
    {
        "id": "kernel_panic",
        "regex": r"(Kernel panic|end Kernel panic|not syncing|sysrq triggered crash)",
        "class": "boot_blocker",
        "severity": "P0",
    },
    {
        "id": "build_error",
        "regex": r"(\berror:|\bFAILED:|ninja: build stopped|Traceback \(most recent call last\))",
        "class": "build",
        "severity": "P1",
    },
    {
        "id": "link_error",
        "regex": r"(undefined reference to|multiple definition of|ld\.lld: error)",
        "class": "link",
        "severity": "P1",
    },
    {
        "id": "hdf_runtime_error",
        "regex": r"(HDF|hdf).*(failed|fail|error|bind|start|load|service)",
        "class": "hdf",
        "severity": "P1",
    },
    {
        "id": "permission_denial",
        "regex": r"(avc: denied|Permission denied|SELinux|capability=.*denied)",
        "class": "permission",
        "severity": "P1",
    },
]


def load_yaml(path):
    if not path:
        return {}
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    if yaml is None:
        return {}
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        return {}
    return data


def dump_data(data):
    if yaml is not None:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(value):
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value.strip("._")[:80] or "slice"


def compile_signatures(taxonomy_path):
    data = load_yaml(taxonomy_path)
    signatures = []
    for item in data.get("signatures", []):
        if isinstance(item, dict) and item.get("id") and item.get("regex"):
            signatures.append(item)
    builtin_ids = {item["id"] for item in signatures}
    for item in BUILTIN_SIGNATURES:
        if item["id"] not in builtin_ids:
            signatures.append(item)

    compiled = []
    for item in signatures:
        try:
            compiled.append((item, re.compile(item["regex"], re.IGNORECASE)))
        except re.error as exc:
            print(
                "warning: skip invalid regex for %s: %s" % (item.get("id"), exc),
                file=sys.stderr,
            )
    return compiled


def read_log_bytes(path):
    data = Path(path).read_bytes()
    lines = data.splitlines(keepends=True)
    offsets = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)
    return data, lines, offsets


def decode_line(raw):
    return raw.decode("utf-8", errors="replace")


def bounded_slice(lines, start, end, max_bytes):
    selected = lines[start:end]
    while selected and sum(len(x) for x in selected) > max_bytes:
        if len(selected) <= 1:
            break
        selected = selected[1:-1] or selected[:1]
    return selected


def write_slice(out_dir, index, log_path, signature_id, line_no, byte_offset, body):
    slice_dir = out_dir / "slices"
    slice_dir.mkdir(parents=True, exist_ok=True)
    name = "slice_%04d_%s_%s_l%d.log" % (
        index,
        safe_name(Path(log_path).stem),
        safe_name(signature_id),
        line_no,
    )
    path = slice_dir / name
    header = [
        "# source: %s\n" % log_path,
        "# signature: %s\n" % signature_id,
        "# line: %d\n" % line_no,
        "# byte_offset: %d\n" % byte_offset,
        "# generated_by: tools/log_slice.py\n",
        "\n",
    ]
    path.write_bytes("".join(header).encode("utf-8") + b"".join(body))
    return path


def slice_logs(args):
    signatures = compile_signatures(args.taxonomy)
    out_dir = Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "taxonomy": str(args.taxonomy) if args.taxonomy else "",
        "context_lines": args.context_lines,
        "logs": [],
        "signature_counts": {},
        "hits": [],
        "slices": [],
    }

    slice_index = 1
    for raw_log in args.log:
        log_path = Path(raw_log)
        data, lines, offsets = read_log_bytes(log_path)
        log_entry = {
            "path": str(log_path),
            "size": len(data),
            "sha256": sha256_file(log_path),
            "line_count": len(lines),
        }
        summary["logs"].append(log_entry)

        per_sig_count = {}
        for idx, raw_line in enumerate(lines):
            text = decode_line(raw_line)
            for sig, regex in signatures:
                sig_id = sig["id"]
                if per_sig_count.get(sig_id, 0) >= args.max_matches_per_signature:
                    continue
                if not regex.search(text):
                    continue
                per_sig_count[sig_id] = per_sig_count.get(sig_id, 0) + 1
                summary["signature_counts"][sig_id] = (
                    summary["signature_counts"].get(sig_id, 0) + 1
                )
                start = max(0, idx - args.context_lines)
                end = min(len(lines), idx + args.context_lines + 1)
                body = bounded_slice(lines, start, end, args.max_bytes_per_slice)
                hit = {
                    "log": str(log_path),
                    "signature_id": sig_id,
                    "class": sig.get("class", ""),
                    "severity": sig.get("severity", ""),
                    "line": idx + 1,
                    "byte_offset": offsets[idx],
                    "text": text.strip()[:300],
                }
                if out_dir:
                    slice_path = write_slice(
                        out_dir, slice_index, log_path, sig_id, idx + 1, offsets[idx], body
                    )
                    hit["slice"] = str(slice_path.relative_to(out_dir))
                    summary["slices"].append(hit["slice"])
                    slice_index += 1
                summary["hits"].append(hit)

    if out_dir:
        (out_dir / "log_slice_summary.yaml").write_text(
            dump_data(summary), encoding="utf-8"
        )
        lines = ["# Top Log Findings", ""]
        if not summary["hits"]:
            lines.append("- No signature hits.")
        for hit in summary["hits"][: args.max_markdown_hits]:
            lines.append(
                "- `%s` %s:%s byte=%s%s"
                % (
                    hit["signature_id"],
                    hit["log"],
                    hit["line"],
                    hit["byte_offset"],
                    " slice=%s" % hit.get("slice") if hit.get("slice") else "",
                )
            )
            if hit.get("text"):
                lines.append("  - `%s`" % hit["text"].replace("`", "'"))
        (out_dir / "top_errors.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        sys.stdout.write(dump_data(summary))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", action="append", required=True, help="log file path")
    parser.add_argument("--taxonomy", help="taxonomy YAML with signatures")
    parser.add_argument("--out-dir", help="write summary and slices to this directory")
    parser.add_argument("--context-lines", type=int, default=25)
    parser.add_argument("--max-matches-per-signature", type=int, default=20)
    parser.add_argument("--max-bytes-per-slice", type=int, default=120000)
    parser.add_argument("--max-markdown-hits", type=int, default=50)
    args = parser.parse_args()
    return slice_logs(args)


if __name__ == "__main__":
    raise SystemExit(main())
