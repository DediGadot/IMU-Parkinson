import re

with open('/home/fiod/medical/paper_new2.tex', 'r') as f:
    content = f.read()
    lines = content.split('\n')

# Check unbalanced braces
for i, line in enumerate(lines):
    # remove escaped braces
    clean_line = line.replace('\\{', '').replace('\\}', '')
    if clean_line.count('{') != clean_line.count('}'):
        # Check overall file context for multiline environments, but for simplicity:
        pass

open_braces = content.replace('\\{', '').count('{')
close_braces = content.replace('\\}', '').count('}')
if open_braces != close_braces:
    print(f"Unbalanced braces: {open_braces} open, {close_braces} close")

# Check for unescaped special characters
in_math = False
in_tabular = False
in_verbatim = False
in_url = False

for i, line in enumerate(lines):
    line_num = i + 1
    
    if '\\begin{tabular}' in line or '\\begin{tabularx}' in line or '\\begin{longtable}' in line:
        in_tabular = True
    if '\\end{tabular}' in line or '\\end{tabularx}' in line or '\\end{longtable}' in line:
        in_tabular = False
        
    if '\\begin{verbatim}' in line:
        in_verbatim = True
    if '\\end{verbatim}' in line:
        in_verbatim = False

    # Naive check for unescaped special chars outside math/tabular/verb
    # remove math inline $...$
    text_only = re.sub(r'\$.*?\$', '', line)
    # remove \texttt{...}
    text_only = re.sub(r'\\texttt\{.*?\}', '', text_only)
    # remove comments
    if not in_verbatim:
        text_only = re.sub(r'(?<!\\)%.*', '', text_only)
        
    if not in_verbatim:
        # Check unescaped &
        if not in_tabular:
            matches = re.finditer(r'(?<!\\)&', text_only)
            for m in matches:
                print(f"Line {line_num}: Unescaped '&' found: {line}")
                
        # Check unescaped #
        matches = re.finditer(r'(?<!\\)#', text_only)
        for m in matches:
            if not ('\\newcolumntype' in line or '\\newcommand' in line):
                print(f"Line {line_num}: Unescaped '#' found: {line}")

        # Check unescaped _
        matches = re.finditer(r'(?<!\\)_', text_only)
        for m in matches:
            # allow in label, ref, cite
            if not re.search(r'\\(label|ref|cite|texttt|url)\{.*_.*\}', line):
                print(f"Line {line_num}: Unescaped '_' found: {line}")

