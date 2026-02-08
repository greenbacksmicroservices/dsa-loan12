#!/usr/bin/env python
"""Simple HTTP test without waiting"""
import subprocess
import sys

# Make HTTP request using curl (Windows compatible)
result = subprocess.run([
    'powershell', '-Command',
    'Invoke-WebRequest -Uri "http://127.0.0.1:8000/admin/all-loans/" -UseBasicParsing | Select-Object -Property StatusCode, RawContentLength'
], capture_output=True, text=True, timeout=5)

print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
print(f"Exit code: {result.returncode}")
