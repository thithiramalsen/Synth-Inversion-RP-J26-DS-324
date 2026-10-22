"""Run C1/C2/C3/C4 together in the separate researcher-only rehearsal service."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent/'backend'))
from c1_researcher_rehearsal import main

if __name__ == '__main__':
    main()
