import os
import re
from fpdf import FPDF
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT

md_file = "/home/apf/.gemini/antigravity-ide/brain/a0b213e8-ee02-4ec7-ada8-6dcaa5732bb9/Final_PyScreen_Report.md"
with open(md_file, "r") as f:
    text = f.read()

# Generate PDF using FPDF
class PDF(FPDF):
    def header(self):
        self.set_font("helvetica", "B", 10)
        self.cell(0, 10, "Android Side channel attacks", border=False, align="C", new_x="LMARGIN", new_y="NEXT")

    def footer(self):
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

pdf = PDF()
pdf.add_page()
pdf.set_auto_page_break(auto=True, margin=15)

pdf.set_font("helvetica", size=11)
for line in text.split('\n'):
    try:
        if line.startswith('# '):
            pdf.set_font("helvetica", "B", 16)
            pdf.multi_cell(w=pdf.epw, h=10, text=line[2:], align="C")
        elif line.startswith('### '):
            pdf.set_font("helvetica", "B", 12)
            pdf.multi_cell(w=pdf.epw, h=10, text=line[4:])
        elif line.startswith('## '):
            pdf.set_font("helvetica", "B", 14)
            pdf.multi_cell(w=pdf.epw, h=10, text=line[3:])
        elif line.startswith('**Project'):
            pdf.set_font("helvetica", "B", 11)
            pdf.multi_cell(w=pdf.epw, h=8, text=line.replace('**', ''))
        elif line.startswith('!['):
            match = re.search(r'\((.*?)\)', line)
            if match:
                img_path = match.group(1)
                if os.path.exists(img_path):
                    pdf.image(img_path, w=pdf.epw)
        elif line.startswith('\\newpage'):
            pdf.add_page()
        elif line.strip() == '---':
            pass
        else:
            if line.strip():
                pdf.set_font("helvetica", size=11)
                clean_line = line.replace('**', '')
                clean_line = clean_line.encode('latin-1', 'replace').decode('latin-1')
                # Add word wrapping safety
                pdf.multi_cell(w=pdf.epw, h=6, text=clean_line)
    except Exception as e:
        print(f"Skipping line due to error: {line}")
        print(e)

pdf.output("/home/apf/.gemini/antigravity-ide/brain/a0b213e8-ee02-4ec7-ada8-6dcaa5732bb9/PyScreen_Report.pdf")
print("Successfully generated files!")
