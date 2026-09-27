#!/usr/bin/env python3
from pathlib import Path

TAG='<script src="/screen-recorder-v4.js"></script>'
FILES=["bot-obfuscated.html","bot.html"]

for name in FILES:
    p=Path(name)
    if not p.exists():
        print(f"skip: {name}")
        continue
    text=p.read_text(encoding="utf-8")
    # Remove earlier recorder tags if present
    for old in [
        '<script src="/screen-recorder.js"></script>',
        '<script src="/screen-recorder-v3.js"></script>',
        '<script src="/screen-recorder-v4.js"></script>'
    ]:
        text=text.replace(f"    {old}\n","")
        text=text.replace(old,"")
    if "</body>" not in text:
        raise SystemExit(f"{name}: </body> not found")
    text=text.replace("</body>",f"    {TAG}\n</body>",1)
    p.write_text(text,encoding="utf-8")
    print(f"patched: {name}")
