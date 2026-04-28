import re
from bs4 import BeautifulSoup
import json

with open("NEW2_clean.html", "r", encoding="utf-8") as f:
    html = f.read()
soup = BeautifulSoup(html, "html.parser")

with open("paper_new2.tex", "r", encoding="utf-8") as f:
    tex = f.read()

# Check A: Table rows numeric cells
html_tables = soup.find_all("table")
print(f"Found {len(html_tables)} HTML tables")

# Check B: Sentences in Discussion or Methods
# Extract text of Discussion and Methods from HTML
discussion = ""
methods = ""
for h2 in soup.find_all("h2"):
    if "Discussion" in h2.text:
        curr = h2.find_next_sibling()
        while curr and curr.name not in ["h1", "h2"]:
            discussion += curr.text + " "
            curr = curr.find_next_sibling()
    if "Methods" in h2.text:
        curr = h2.find_next_sibling()
        while curr and curr.name not in ["h1", "h2"]:
            methods += curr.text + " "
            curr = curr.find_next_sibling()

# Check C: Figure caption text
html_captions = [cap.text for cap in soup.find_all("figcaption")]
print(f"Found {len(html_captions)} HTML captions")

# Output findings to a file so we can read them
with open("compare_results.json", "w") as f:
    json.dump({"html_tables": len(html_tables), "html_captions": len(html_captions)}, f)
