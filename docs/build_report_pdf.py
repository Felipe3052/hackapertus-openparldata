"""
Adapted from the team's Fact Attack 2026 repository.
Render technical_report.md to the submission PDF (max. 6 pages) with headless Chrome or Edge.

    pip install -e '.[report]'
    python docs/build_report_pdf.py            # -> TokenTell_Report.pdf (repository root)
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "technical_report.md"
TARGET = ROOT / "TokenTell_Report.pdf"
MAX_PAGES = 6

CSS = """
@page { size: A4; margin: 15mm 16mm 14mm 16mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; line-height: 1.4; color: #111; }
h1 { font-size: 15pt; margin: 0 0 6px; }
h2 { font-size: 12pt; margin: 12px 0 4px; border-bottom: 1px solid #bbb; padding-bottom: 2px; }
h3 { font-size: 10.4pt; margin: 9px 0 3px; }
h1, h2, h3 { break-after: avoid; page-break-after: avoid; }
p, ul, ol { margin: 3px 0 5px; }
ul, ol { padding-left: 18px; }
li { margin: 1px 0; }
hr { display: none; }
table { border-collapse: collapse; margin: 4px 0 7px; font-size: 9.2pt; width: 100%; page-break-inside: avoid; }
table.long { page-break-inside: auto; }
tr { page-break-inside: avoid; }
th, td { border: 1px solid #ccc; padding: 2px 5px; vertical-align: top; }
th { background: #f0f0f0; }
pre { font-size: 8.4pt; line-height: 1.2; background: #f6f6f6; padding: 5px 7px; margin: 4px 0 6px; page-break-inside: avoid; }
code { font-family: Consolas, monospace; font-size: 8.6pt; }
a { color: #0645ad; text-decoration: none; }
"""

BROWSERS = [
    "chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "msedge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser() -> str:
    for candidate in BROWSERS:
        found = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if found:
            return found
    sys.exit("No Chrome/Edge/Chromium found for printing the PDF.")


def main() -> None:
    body = markdown.markdown(
        SOURCE.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "sane_lists"]
    )
    # Long tables may break across pages (row by row); short ones stay together
    body = re.sub(
        r"<table>(.*?)</table>",
        lambda m: (
            ("<table class='long'>" if m.group(1).count("<tr>") > 10 else "<table>")
            + m.group(1)
            + "</table>"
        ),
        body,
        flags=re.S,
    )
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{body}</body></html>"
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "report.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run(
            [
                find_browser(),
                "--headless=new",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={TARGET}",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
        )

    from pypdf import PdfReader

    pages = len(PdfReader(str(TARGET)).pages)
    print(
        f"{TARGET.relative_to(ROOT)}: {pages} pages"
        + ("" if pages <= MAX_PAGES else f"  (over the {MAX_PAGES}-page limit!)")
    )


if __name__ == "__main__":
    main()
