import re
from bs4 import BeautifulSoup

def clean_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['style', 'script', 'head', 'title', 'meta']):
        tag.decompose()
    paras = soup.find_all('p')
    return [p.get_text(separator=' ').strip() for p in paras if p.get_text(separator=' ').strip() and 'author' not in p.get_text().lower()]

with open("NEW2_clean.html", "r") as f:
    html_text = f.read()

html_paras = clean_html(html_text)

with open("paper_new2.tex", "r") as f:
    tex_text = f.read()

# very rough extraction
tex_paras = re.split(r'\n\s*\n', tex_text)
tex_paras = [p.replace('\n', ' ').strip() for p in tex_paras if p.strip() and not p.startswith('%') and not p.startswith('\\begin') and not p.startswith('\\end') and not p.startswith('\\caption')]

# Write output to investigate
with open("compare.txt", "w") as f:
    for i, hp in enumerate(html_paras):
        f.write(f"HTML P{i}:\n{hp}\n\n")
        # try to find match in tex
        match = [tp for tp in tex_paras if hp[:50] in tp]
        if match:
            f.write(f"TEX Match:\n{match[0]}\n\n")
        else:
            f.write(f"TEX Match: NONE FOUND (Check manually)\n\n")
