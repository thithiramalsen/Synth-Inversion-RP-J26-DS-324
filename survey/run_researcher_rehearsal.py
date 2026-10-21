"""Run the separate, labelled researcher-only C1 rehearsal."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent/'backend'))
from c1_researcher_rehearsal import main

if __name__ == '__main__':
    main()
