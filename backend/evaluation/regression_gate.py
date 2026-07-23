"""Runs the full pipeline against the golden dataset and fails (non-zero exit) if the
judge score drops below a threshold vs. the last known-good run. Wired into CI in
Phase 18. Built in Phase 9."""
