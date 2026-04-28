import re

with open('paper_new2.tex', 'r') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    line_num = i + 1
    
    # Check for raw HTML entities
    html_entities = re.findall(r'&[a-zA-Z0-9]+;', line)
    if html_entities:
        print(f"Line {line_num}: HTML entity found: {html_entities}")
        
    # Check for unescaped _ outside math/verbatim/texttt/ref/label
    # A bit hard to do accurately with regex, but let's try a simple heuristic
    # Remove math mode $...$ and \(...\) and \[...\]
    # Remove \texttt{...} and \url{...} and \label{...} and \ref{...}
    cleaned = re.sub(r'\$.*?\$', '', line)
    cleaned = re.sub(r'\\texttt\{.*?\}', '', cleaned)
    cleaned = re.sub(r'\\label\{.*?\}', '', cleaned)
    cleaned = re.sub(r'\\ref\{.*?\}', '', cleaned)
    cleaned = re.sub(r'\\includegraphics\[.*?\]\{.*?\}', '', cleaned)
    cleaned = re.sub(r'\\begin\{.*?\}', '', cleaned)
    cleaned = re.sub(r'\\end\{.*?\}', '', cleaned)
    cleaned = re.sub(r'\\cite\{.*?\}', '', cleaned)
    
    # Now check for unescaped _ 
    unescaped_underscore = re.findall(r'(?<!\\)_', cleaned)
    if unescaped_underscore:
        print(f"Line {line_num}: Potential unescaped underscore in: {cleaned.strip()}")

    # Check for unescaped &
    # It's used as column separator in tabular. Let's ignore tabular lines or check roughly
    if not ('&' in line and ('tabular' in line or '&' in line and '\\\\' in line)):
        if re.search(r'(?<!\\)&', line) and 'begin{tabular' not in line and 'end{tabular' not in line:
            # might be valid if it's a table row without \\ on same line, but worth checking
            pass

