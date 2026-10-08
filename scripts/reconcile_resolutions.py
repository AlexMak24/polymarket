#!/usr/bin/env python3
"""Shim: forwards to polymarket_reconcile.py."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parents[1] / 'polymarket_reconcile.py'), run_name='__main__')
