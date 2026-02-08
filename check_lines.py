#!/usr/bin/env python
with open('core/urls.py', 'rb') as f:
    lines = f.readlines()
    print("Checking lines 67-70 (subadmin dashboard area):\n")
    for i in range(66, 70):
        line_bytes = lines[i]
        line_str = line_bytes.decode('utf-8', errors='replace')
        print(f"Line {i+1}:")
        print(f"  Bytes: {line_bytes}")
        print(f"  Text:  {line_str.rstrip()}")
        print()
