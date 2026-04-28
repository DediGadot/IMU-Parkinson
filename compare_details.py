import re
from bs4 import BeautifulSoup

def tex_clean(text):
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    text = re.sub(r'[{}]', '', text)
    text = re.sub(r'%.*?\n', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

with open("NEW2_clean.html", "r", encoding="utf-8") as f:
    html_soup = BeautifulSoup(f.read(), "html.parser")

with open("paper_new2.tex", "r", encoding="utf-8") as f:
    tex_lines = f.readlines()

def get_tex_table(tex_lines):
    tables = []
    curr_table = []
    in_table = False
    start_line = -1
    for i, line in enumerate(tex_lines):
        if "\\begin{table" in line or "\\begin{table*}" in line or "\\begin{longtable}" in line:
            in_table = True
            start_line = i
            curr_table = [line]
        elif in_table:
            curr_table.append(line)
            if "\\end{table" in line or "\\end{table*}" in line or "\\end{longtable}" in line:
                in_table = False
                tables.append({"start_line": start_line, "lines": curr_table})
                curr_table = []
    return tables

tex_tables = get_tex_table(tex_lines)
html_tables = html_soup.find_all("table")

print(f"Found {len(tex_tables)} tex tables, {len(html_tables)} html tables")

for t_idx, html_t in enumerate(html_tables):
    if t_idx >= len(tex_tables): break
    tex_t = tex_tables[t_idx]
    
    html_rows = html_t.find_all("tr")
    
    tex_rows = []
    for j, line in enumerate(tex_t["lines"]):
        if "&" in line and "\\\\" in line:
            tex_rows.append((tex_t["start_line"] + j, line))
    
    # print(f"Table {t_idx+1}: HTML={len(html_rows)} rows, TEX={len(tex_rows)} rows")
    # Compare numbers in rows
    for h_row, (tex_line_num, tex_row) in zip(html_rows[1:], tex_rows[1:]): # skip header roughly
        html_cells = h_row.find_all(["th", "td"])
        html_nums = []
        for c in html_cells:
            nums = re.findall(r'-?\d+\.?\d*', c.get_text())
            html_nums.extend(nums)
        
        tex_nums = re.findall(r'-?\d+\.?\d*', tex_row)
        # Filter out tex specific numbers if any, like label numbers, but usually just in data
        
        # We need a smarter way because formatting might differ (e.g., 0.864 vs .864)
        html_n = [float(n) for n in html_nums if float(n) != 0 or '0' in n]
        try:
            tex_n = [float(n) for n in tex_nums if float(n) != 0 or '0' in n]
        except:
            continue
        
        if html_n != tex_n and len(html_n) > 0 and len(tex_n) > 0:
            print(f"Table {t_idx+1} mismatch near line {tex_line_num+1}:")
            print(f"  HTML: {html_n}")
            print(f"  TEX : {tex_n}")
            print(f"  TEX LINE: {tex_row.strip()}")

# Check Subsections
print("\n=== Subsections ===")
html_subs = html_soup.find_all(["h1", "h2", "h3"])
for h in html_subs:
    text = h.get_text().strip()
    match = re.match(r'^(\d+\.\d+(\.\d+)?)\s+', text)
    if match:
        num = match.group(1)
        # See if this heading text exists in tex with same num
        title = text[len(num):].strip()
        found = False
        for i, line in enumerate(tex_lines):
            if ("\\section" in line or "\\subsection" in line or "\\subsubsection" in line) and title.lower()[:15] in line.lower():
                # check if numbering might be wrong
                # standard LaTeX auto-numbers, but wait, maybe there's a hardcoded number?
                # we just need to see if the structure matches
                pass

# Check Captions
print("\n=== Captions ===")
html_caps = [fig.find("figcaption") for fig in html_soup.find_all(["figure", "div"]) if fig.find("figcaption")]
for cap in html_caps:
    cap_text = cap.get_text().strip()
    # Find in tex
    cap_clean = re.sub(r'\s+', ' ', cap_text)[:50]
    found = False
    for i, line in enumerate(tex_lines):
        if cap_clean in re.sub(r'\s+', ' ', line):
            found = True
            break
    if not found:
        # try 30 chars
        cap_clean = re.sub(r'\s+', ' ', cap_text)[:30]
        for i, line in enumerate(tex_lines):
            if cap_clean in re.sub(r'\s+', ' ', line):
                found = True
                print(f"Caption might be truncated/rephrased near line {i+1}: {cap_clean}")
                break

# Check Paragraphs
print("\n=== Paragraphs ===")
# extract paragraphs from html
html_ps = []
for h2 in html_soup.find_all("h2"):
    if "Methods" in h2.get_text() or "Discussion" in h2.get_text():
        curr = h2.find_next_sibling()
        while curr and curr.name not in ["h1", "h2"]:
            if curr.name == "p":
                html_ps.append(re.sub(r'\s+', ' ', curr.get_text().strip()))
            curr = curr.find_next_sibling()

tex_full = "".join(tex_lines)
tex_clean_full = re.sub(r'\s+', ' ', tex_full)

for p in html_ps:
    # check first 50 chars
    prefix = p[:50]
    # Check if prefix in tex
    found = False
    for i, line in enumerate(tex_lines):
        if prefix in line:
            found = True
            break
    if not found:
        print(f"Paragraph missing or rewritten in tex? Starts with: {prefix}")
