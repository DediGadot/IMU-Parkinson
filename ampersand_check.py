in_tabular = False
with open('/home/fiod/medical/paper_new2.tex', 'r') as f:
    for i, line in enumerate(f):
        if '\\begin{tabular}' in line or '\\begin{tabularx}' in line or '\\begin{longtable}' in line:
            in_tabular = True
        if '\\end{tabular}' in line or '\\end{tabularx}' in line or '\\end{longtable}' in line:
            in_tabular = False
        
        if not in_tabular:
            if '&' in line and '\\&' not in line:
                print(f"{i+1}: {line.strip()}")
