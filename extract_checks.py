import re
from bs4 import BeautifulSoup
import string

def clean_text(text):
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

with open("NEW2_clean.html", "r", encoding="utf-8") as f:
    html_soup = BeautifulSoup(f.read(), "html.parser")

with open("paper_new2.tex", "r", encoding="utf-8") as f:
    tex_lines = f.readlines()
tex_text = "".join(tex_lines)

# 1. Check Tables
print("=== Checking Tables ===")
html_tables = html_soup.find_all("table")
for i, table in enumerate(html_tables):
    rows = table.find_all("tr")
    print(f"HTML Table {i+1}: {len(rows)} rows")
    for r in rows:
        cells = r.find_all(["th", "td"])
        cell_texts = [clean_text(c.get_text()) for c in cells]
        nums = [re.findall(r'-?\d+\.?\d*', c) for c in cell_texts]
        # just print a few to see if we can find them in tex
        # Wait, let's write a smarter checker

# 2. Extract Methods and Discussion from HTML
methods_text = ""
discussion_text = ""
for h2 in html_soup.find_all("h2"):
    if "Methods" in h2.get_text():
        curr = h2.find_next_sibling()
        while curr and curr.name not in ["h1", "h2"]:
            if curr.name == "p":
                methods_text += curr.get_text() + " "
            curr = curr.find_next_sibling()
    elif "Discussion" in h2.get_text():
        curr = h2.find_next_sibling()
        while curr and curr.name not in ["h1", "h2"]:
            if curr.name == "p":
                discussion_text += curr.get_text() + " "
            curr = curr.find_next_sibling()

# Save for manual or script-based comparison
with open("html_methods.txt", "w") as f: f.write(methods_text)
with open("html_discussion.txt", "w") as f: f.write(discussion_text)

# 3. Figure captions
captions = []
for fig in html_soup.find_all(["figure", "div"]):
    cap = fig.find("figcaption")
    if cap: captions.append(clean_text(cap.get_text()))
with open("html_captions.txt", "w") as f: f.write("\n".join(captions))

print("Extraction complete.")
