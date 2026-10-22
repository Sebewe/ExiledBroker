"""Fetch external data into data/raw and data/processed.

Every step is safe to interrupt and re-run: outputs are written to a temporary
path and renamed into place only when complete, so a finished file is its own
completion marker.
"""
