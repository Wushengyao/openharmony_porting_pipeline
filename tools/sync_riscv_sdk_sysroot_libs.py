#!/usr/bin/env python3
"""Sync tiny RISC-V musl archive libs into the OH SDK sysroot.

Some OH6.x RISC-V source-built XTS HAPs use the SDK/Hvigor path rather than
the normal GN sysroot path. If the SDK sysroot has crt objects and libm.a but
not libdl.a/libpthread.a, clang can fail while resolving libunwind.a deplibs.

This helper copies same-workspace musl archives from out/<product>/obj into
prebuilts/ohos-sdk only when --apply is provided.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


DEFAULT_LIBS = ("libdl.a", "libpthread.a")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="OpenHarmony workspace root")
    parser.add_argument("--product", default="musepaper2", help="out/<product> name")
    parser.add_argument("--api", default="23", help="prebuilts/ohos-sdk/linux/<api> level")
    parser.add_argument("--arch-triple", default="riscv64-linux-ohos")
    parser.add_argument("--lib", action="append", dest="libs", help="archive name to sync")
    parser.add_argument("--apply", action="store_true", help="copy files instead of dry-run")
    parser.add_argument("--out", help="write JSON result to this path")
    args = parser.parse_args()

    root = Path(args.workspace).resolve()
    libs = tuple(args.libs or DEFAULT_LIBS)
    src_dir = root / "out" / args.product / "obj" / "third_party" / "musl" / "usr" / "lib" / args.arch_triple
    dst_dir = root / "prebuilts" / "ohos-sdk" / "linux" / args.api / "native" / "sysroot" / "usr" / "lib" / args.arch_triple

    result = {
        "workspace": str(root),
        "product": args.product,
        "api": args.api,
        "arch_triple": args.arch_triple,
        "apply": args.apply,
        "source_dir": str(src_dir),
        "dest_dir": str(dst_dir),
        "ok": True,
        "items": [],
    }

    if not src_dir.is_dir():
        result["ok"] = False
        result["error"] = f"missing source directory: {src_dir}"
    elif not dst_dir.is_dir():
        result["ok"] = False
        result["error"] = f"missing destination directory: {dst_dir}"
    else:
        for lib in libs:
            src = src_dir / lib
            dst = dst_dir / lib
            item = {"lib": lib, "source": str(src), "dest": str(dst)}
            if not src.is_file():
                item["status"] = "missing_source"
                result["ok"] = False
            else:
                item["source_size"] = src.stat().st_size
                item["source_sha256"] = sha256(src)
                if dst.exists():
                    item["dest_size_before"] = dst.stat().st_size
                    item["dest_sha256_before"] = sha256(dst)
                else:
                    item["dest_size_before"] = None
                    item["dest_sha256_before"] = None
                if args.apply:
                    shutil.copy2(src, dst)
                    item["dest_size_after"] = dst.stat().st_size
                    item["dest_sha256_after"] = sha256(dst)
                    item["status"] = "copied" if item["dest_sha256_before"] != item["dest_sha256_after"] else "unchanged"
                else:
                    item["status"] = "would_copy" if not dst.exists() else "would_check_existing"
            result["items"].append(item)

    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
