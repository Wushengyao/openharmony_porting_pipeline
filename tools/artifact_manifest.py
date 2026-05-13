#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path

def sha256(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

ap=argparse.ArgumentParser()
ap.add_argument('--out', required=True)
args=ap.parse_args()
out=Path(args.out)
items=[]
for p in sorted(out.rglob('*')):
    if p.is_file():
        items.append({'path':str(p.relative_to(out)), 'size':p.stat().st_size, 'sha256':sha256(p)})
(out/'06_audit').mkdir(parents=True, exist_ok=True)
(out/'06_audit/artifact_manifest.json').write_text(json.dumps({'files':items}, indent=2, ensure_ascii=False), encoding='utf-8')
