import pymupdf4llm
import pathlib
import sys
import io

md_text = pymupdf4llm.to_markdown("test3.pdf")

# Ensure console can handle UTF-8 output on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

print(md_text)

pathlib.Path("4llm-output3.md").write_bytes(md_text.encode('utf-8'))
