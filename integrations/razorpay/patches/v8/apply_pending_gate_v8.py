#!/usr/bin/env python3
"""Hash-pinned, rollback-capable additive v8 patch over the v7 handoff."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime, timezone

HERE=Path(__file__).resolve().parent
PAYLOAD=HERE/'payload'
REPLACEMENTS={
    'backend/app/models/riskops_operation.py': 'f4e959cd5d04d74e85dc30a79b8f4fa6eb9ecbe11128b40233e1235576328702',
    'backend/app/services/riskops_operation_journal.py': 'bfcf30b92e104275cf6eb82622d94fa6f1e5f584262c7512c0a8541fefaa2512',
}
NEW='migrations/versions/20261023_riskops_pending_gate_v8.py'
FROZEN='data/benchmarks/razorpay-risk-verifier-v24.freeze.json'

def digest(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()

def validate(repo:Path)->list[str]:
    repo=repo.resolve(); errors=[]
    for rel, sha in REPLACEMENTS.items():
        target=repo/rel
        if not target.is_file() or digest(target)!=sha:
            errors.append(f'v7 baseline mismatch: {rel}')
    if (repo/NEW).exists():errors.append('v8 migration exists (refusing overwrite or repeat install)')
    if not (repo/'migrations/versions/20261023_riskops_operations_v7.py').is_file():
        errors.append('v7 migration missing')
    if not (repo/'backend/app/main.py').is_file() or not (repo/'backend/app/routers/riskops_security_routes.py').is_file():
        errors.append('secure RiskOps routes missing')
    try:
        manifest=json.loads((repo/FROZEN).read_text(encoding='utf-8'))
        records=manifest['files']
        if manifest['verifier_version']!='razorpay-non-delivery-v24' or len(records)!=20:
            errors.append('unexpected v24 freeze identity / file count')
        else:
            for item in records:
                target=(repo/item['path']).resolve()
                if not target.is_relative_to(repo) or not target.is_file() or digest(target)!=item['sha256']:
                    errors.append('frozen v24 file differs: '+str(item['path']))
    except (KeyError,OSError,ValueError,TypeError) as exc:
        errors.append('frozen v24 manifest unavailable: '+type(exc).__name__)
    return errors

def install(repo:Path,dry_run:bool=False)->int:
    repo=repo.resolve()
    if not repo.is_dir():print('REFUSED: repository directory does not exist');return 2
    errors=validate(repo)
    if errors:
        print('REFUSED:','\n - '.join(errors),sep='\n - ');return 3
    if dry_run:
        print('DRY RUN PASS: v7 hashes and 20/20 frozen v24 files verified; no writes');return 0
    backup=repo/'.mulyankan-resolve-backups'/('pending-gate-v8-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    copied=[]
    try:
        for rel in [*REPLACEMENTS,NEW]:
            source=PAYLOAD/rel;target=repo/rel
            if not source.is_file():raise RuntimeError('patch file missing: '+rel)
            previous=None
            if target.exists():
                previous=backup/rel;previous.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(target,previous)
            target.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.pending-v8-',delete=False) as f:
                temp=Path(f.name);f.write(source.read_bytes())
            try:os.replace(temp,target)
            finally:temp.unlink(missing_ok=True)
            copied.append((target,previous))
            if digest(source)!=digest(target):raise RuntimeError('post-write hash differs: '+rel)
        # Verify immutable verifier again, even if the installer failed before.
        manifest=json.loads((repo/FROZEN).read_text(encoding='utf-8'))
        for item in manifest['files']:
            if digest(repo/item['path']) != item['sha256']:
                raise RuntimeError('frozen verifier changed during install')
    except Exception as exc:
        for target,previous in reversed(copied):
            if previous is not None:shutil.copy2(previous,target)
            else:target.unlink(missing_ok=True)
        print('INSTALL FAILED and file changes rolled back:',type(exc).__name__,str(exc));return 4
    print('PASS: v8 source installed; frozen v24 verified 20/20')
    print('Backup:',backup)
    print('NEXT: stop all old workers, apply v8 Alembic migration, then start v8 workers')
    return 0

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('repo',type=Path)
    parser.add_argument('--dry-run',action='store_true')
    options=parser.parse_args()
    sys.exit(install(options.repo,options.dry_run))
