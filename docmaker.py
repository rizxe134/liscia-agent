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

def chunks(rows, n=6):
    return [rows[i:i + n] for i in range(0, len(rows), n)] or [[]]

def make_pptx(path, title, summary, columns, rows, source, today):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    prs = Presentation(); prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = title; s.placeholders[1].text = f"{today}\nMade by Liscia Agent"
    if summary:
        s = prs.slides.add_slide(prs.slide_layouts[1]); s.shapes.title.text = "Summary"
        tf = s.placeholders[1].text_frame; tf.text = summary
        for p in tf.paragraphs:
            for r in p.runs: r.font.size = Pt(20)
    parts = chunks(rows, 6)
    for i, part in enumerate(parts if rows else []):
        s = prs.slides.add_slide(prs.slide_layouts[5])
        s.shapes.title.text = title if len(parts) == 1 else f"{title} ({i + 1}/{len(parts)})"
        if columns:
            ncol = len(columns)
            tbl = s.shapes.add_table(len(part) + 1, ncol, Inches(0.5), Inches(1.6), Inches(12.3), Inches(0.6) * (len(part) + 1)).table
            for c, name in enumerate(columns):
                tbl.cell(0, c).text = name
            for r, row in enumerate(part, 1):
                for c in range(ncol):
                    tbl.cell(r, c).text = row[c] if c < len(row) else ""
                    for p in tbl.cell(r, c).text_frame.paragraphs:
                        for run in p.runs: run.font.size = Pt(16)
        else:
            tb = s.shapes.add_textbox(Inches(0.7), Inches(1.6), Inches(12), Inches(5)).text_frame
            tb.text = "\n".join("• " + " - ".join(r) for r in part)
    s = prs.slides.add_slide(prs.slide_layouts[1]); s.shapes.title.text = "Source"
    s.placeholders[1].text_frame.text = (source or "web search") + f"\nRetrieved {today}. Check important numbers at the source."
    prs.save(path)

def make(kind, title, summary="", columns=(), rows=(), source="", folder=None, today=None, report=None):
    """kind: docx | xlsx | pptx | txt. report = {"intro": str, "items": [{"name","text"}], "conclusion": str} for a fuller Word report.
    Returns the saved path."""
    today = today or datetime.date.today().strftime("%B %d, %Y")
    columns = [str(c) for c in (columns or [])]; rows = [[("" if v is None else str(v)) for v in r] for r in (rows or [])]
    path = unique_path(safe_name(title), "." + kind, folder)
    if kind == "docx":
        from docx import Document
        d = Document(); d.add_heading(title, 0)
        d.add_paragraph(f"Date: {today}")
        if source: d.add_paragraph(f"Source: {source}")
        if report and report.get("intro"): d.add_heading("Introduction", 1); d.add_paragraph(report["intro"])
        elif summary: d.add_heading("Summary", 1); d.add_paragraph(summary)
        if rows and columns:
            d.add_heading("Data", 1)
            t = d.add_table(rows=1, cols=len(columns)); t.style = "Light Grid Accent 1"
            for i, c in enumerate(columns): t.rows[0].cells[i].text = c
            for r in rows:
                cells = t.add_row().cells
                for i in range(len(columns)): cells[i].text = r[i] if i < len(r) else ""
        if report and report.get("items"):
            d.add_heading("Details", 1)
            for it in report["items"]:
                d.add_heading(str(it.get("name") or ""), 2); d.add_paragraph(str(it.get("text") or ""))
        if report and report.get("conclusion"): d.add_heading("Conclusion", 1); d.add_paragraph(report["conclusion"])
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
    elif kind == "pptx":
        make_pptx(path, title, summary, columns, rows, source, today)
    else:
        lines = [title, "=" * len(title), f"Date: {today}"] + ([f"Source: {source}"] if source else []) + ["", summary, ""]
        if columns: lines.append(" | ".join(columns))
        lines += [" | ".join(r) for r in rows]
        with open(path, "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
    return path

def open_file(path, run=None):
    try:
        if sys.platform.startswith("win"): os.startfile(path)  # default app (Word / Excel / PowerPoint / Notepad)
        elif sys.platform == "darwin": (run or subprocess.run)(["open", path])
        else: (run or subprocess.run)(["xdg-open", path])
        return True
    except Exception:
        return False
