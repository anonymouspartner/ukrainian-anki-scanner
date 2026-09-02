"""Makes the modules under test importable from the repository root.

The app is a flat set of scripts rather than an installed package, so without
this the tests only resolve `anki_export` and friends under `python -m pytest`
(which puts the working directory on sys.path) and fail under a bare `pytest`.
pytest imports this file before collection and prepends its directory, so both
invocations work.
"""
