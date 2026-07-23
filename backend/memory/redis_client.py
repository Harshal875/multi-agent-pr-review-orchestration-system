"""Session-level cache so identical diffs don't re-embed or re-query retrieval within
a run. Distinct from the ARQ queue's Redis usage. Built in Phase 6."""
