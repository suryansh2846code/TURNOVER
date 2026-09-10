"""Pin the test environment BEFORE any lodestone module (and thus `.env`) loads.

Tests must be fully offline and deterministic. Individual test modules used
`os.environ.setdefault(...)`, which silently loses to a developer's `.env`
(e.g. LODESTONE_MODEL_PROVIDER=claude-code, EMBEDDING_PROVIDER=local) as soon
as another module imports `lodestone.config` first — making results depend on
collection order and hitting a real model. conftest.py is imported before every
test module, so setting the vars here is authoritative.
"""
import os
import tempfile

os.environ["LODESTONE_MODEL_PROVIDER"] = "mock"
os.environ["LODESTONE_MODEL_NAME"] = "mock-1"
os.environ["LODESTONE_EMBEDDING_PROVIDER"] = "hash"
os.environ.setdefault("LODESTONE_HOME", tempfile.mkdtemp(prefix="lodestone-tests-"))
