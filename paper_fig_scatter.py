"""
Compatibility wrapper for the maintained paper stats-figure pipeline.

Historically this script retrained a LightGBM model from scratch and wrote
scatter/residual figures using hard-coded /root paths. The paper now uses
the cached prediction artifacts summarized in `paper_fig_stats.py`, so this
wrapper simply forwards to that script with the current interpreter.
"""
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parent
    target = root / "paper_fig_stats.py"
    print(f"Delegating to {target.name} using cached paper-result artifacts...")
    subprocess.run([sys.executable, str(target)], check=True)


if __name__ == "__main__":
    main()
