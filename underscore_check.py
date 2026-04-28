with open('/home/fiod/medical/paper_new2.tex', 'r') as f:
    for i, line in enumerate(f):
        if '_' in line and '\\_' not in line:
            # Let's print it to see if it's outside math mode
            print(f"{i+1}: {line.strip()}")
