"""Reproduce source-level v8 regression checks without dependencies on Razorpay."""
from pathlib import Path
import compileall
import subprocess
import sys
root=Path(__file__).resolve().parents[1]
if not compileall.compile_dir(str(root/'payload'),quiet=1):raise SystemExit('python compile failed')
if not compileall.compile_file(str(root/'apply_pending_gate_v8.py'),quiet=1):raise SystemExit('installer compile failed')
result=subprocess.run([sys.executable,str(root/'tests/test_pending_gate.py')],check=False)
raise SystemExit(result.returncode)
