#!/usr/bin/env python3
"""Regenerate the sample data the example workflows run on.

The file-triage example moves files around, so run this before
re-running the examples to get a fresh, identical starting state:

    python3 reset_samples.py
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sayflow import write_samples  # noqa: E402


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    sample = os.path.join(base, "sample")
    if os.path.isdir(sample):
        shutil.rmtree(sample)
    write_samples(base)
    print("Sample data reset under {}/".format(os.path.relpath(sample)))


if __name__ == "__main__":
    main()
