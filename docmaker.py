"""Local document output: .docx (Word), .xlsx (Excel) or .txt, saved to Documents/Liscia Agent and opened."""
import datetime, os, re, subprocess, sys

def out_dir():
    d = os.path.join(os.path.expanduser("~"), "Documents", "Liscia Agent")
    os.makedirs(d, exist_ok=True); return d

def safe_name(title):
    n = re.sub(r"[^\w\- ]+", "", title or "Liscia Agent").strip()[:60] or "Liscia Agent"
    return n

def unique_path(base, ext, folder=None):
    folder = folder or out_dir(); p = os.path.join(folder, base + ext); i = 2
    while os.path.exists(p): p = os.path.join(folder, f"{base} ({i}){ext}"); i += 1
    return p

def make(kind, title, summary="", columns=(), rows=(), source="", folder=None, today=None):
    """kind: docx | xlsx | txt. Returns the saved path."""
    today = today or datetime.date.today().strftime("%B %d, %Y")
    columns = [str(c) for c in (columns or [])]; rows = [[("" if v is None else str(v)) for v in r] for r in (rows or [])]
    path = unique_path(safe_name(title), "." + kind, folder)
    if kind == "docx":
        from docx import Document
        d = Document(); d.add_heading(title, 0)
        d.add_paragraph(f"Date: {today}")
        if source: d.add_paragraph(f"Source: {source}")
        if summary: d.add_heading("Summary", 1); d.add_paragraph(summary)
        if rows and columns:
            d.add_heading("Data", 1)
            t = d.add_table(rows=1, cols=len(columns)); t.style = "Light Grid Accent 1"
            for i, c in enumerate(columns): t.rows[0].cells[i].text = c
            for r in rows:
                cells = t.add_row().cells
                for i in range(len(columns)): cells[i].text = r[i] if i < len(r) else ""
        d.add_paragraph("\nMade by Liscia Agent from the page above; check important numbers at the source.")
        d.save(path)
    elif kind == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font
        wb = Workbook(); ws = wb.active; ws.title = "Data"
        ws.append([title]); ws["A1"].font = Font(bold=True, size=14)
        ws.append([f"Date: {today}"]); ws.append([f"Source: {source}"] if source else [])
        ws.append([])
        if columns:
            ws.append(columns)
            for c in ws[ws.max_row]: c.font = Font(bold=True)
        for r in rows: ws.append(r)
        if summary: s = wb.create_sheet("Summary"); s.append([summary])
        wb.save(path)
    else:
        lines = [title, "=" * len(title), f"Date: {today}"] + ([f"Source: {source}"] if source else []) + ["", summary, ""]
        if columns: lines.append(" | ".join(columns))
        lines += [" | ".join(r) for r in rows]
        with open(path, "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
    return path

def open_file(path, run=None):
    try:
        if sys.platform.startswith("win"): os.startfile(path)  # default app (Word / Excel / Notepad)
        elif sys.platform == "darwin": (run or subprocess.run)(["open", path])
        else: (run or subprocess.run)(["xdg-open", path])
        return True
    except Exception:
        return False
