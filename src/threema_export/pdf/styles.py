from __future__ import annotations
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def build_styles():
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    h3 = styles["Heading3"]
    mono = ParagraphStyle("mono", parent=normal, fontName="Courier", fontSize=8.5, leading=10.5)
    return {"normal": normal, "h1": h1, "h2": h2, "h3": h3, "mono": mono}
