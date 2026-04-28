import re
from bs4 import BeautifulSoup
import sys

with open("NEW2_clean.html", "r", encoding="utf-8") as f:
    html = f.read()
soup = BeautifulSoup(html, "html.parser")

with open("paper_new2.tex", "r", encoding="utf-8") as f:
    tex = f.read()

def normalize(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text).lower()

tex_norm = normalize(tex)

def check_text(text_to_check, context=""):
    sentences = re.split(r'(?<=[a-zA-Z0-9])\. ', text_to_check)
    for s in sentences:
        s_clean = re.sub(r'\s+', ' ', s).strip()
        if len(s_clean) < 15: continue
        prefix = normalize(s_clean[:35])
        if prefix not in tex_norm:
            print(f"MISSING {context}: {s_clean}")

# Discussion & Methods sentences
for h2 in soup.find_all("h2"):
    if "Methods" in h2.get_text() or "Discussion" in h2.get_text():
        curr = h2.find_next_sibling()
        while curr and curr.name not in ["h1", "h2"]:
            if curr.name == "p":
                check_text(curr.get_text(), context="Sentence")
            curr = curr.find_next_sibling()

# Captions
for fig in soup.find_all(["figure", "div"]):
    cap = fig.find("figcaption")
    if cap:
        check_text(cap.get_text(), context="Caption")

# Tables - specifically looking for structural or number mismatches
# just extracting numbers
def get_numbers(t):
    return re.findall(r'-?\d+\.?\d*', t)

html_tables = soup.find_all("table")

# Find tex tables roughly
tex_lines = tex.split('\n')
in_table = False
tex_tables = []
curr = []
for line in tex_lines:
    if "\\begin{table" in line or "\\begin{table*" in line or "\\begin{longtable}" in line:
        in_table = True
        curr = []
    if in_table:
        curr.append(line)
        if "\\end{table" in line or "\\end{table*" in line or "\\end{longtable}" in line:
            in_table = False
            tex_tables.append("\n".join(curr))

for i, ht in enumerate(html_tables):
    if i >= len(tex_tables): break
    tt = tex_tables[i]
    hn = get_numbers(ht.get_text())
    tn = get_numbers(re.sub(r'\\[a-zA-Z]+', '', tt).replace('{', '').replace('}', ''))
    # Very coarse comparison: if counts match, are there diffs?
    
    # check Table caption
    cap = ht.find("caption")
    if cap: check_text(cap.get_text(), context=f"Table {i+1} Caption")

# Subsections
for h in soup.find_all(["h1", "h2", "h3"]):
    text = h.get_text().strip()
    match = re.match(r'^(\d+\.\d+(\.\d+)?)\s+', text)
    if match:
        check_text(text[len(match.group(1)):].strip(), context=f"Heading {match.group(1)}")
