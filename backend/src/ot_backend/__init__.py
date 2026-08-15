"""mtg-search FastAPI service package."""

# Single source of truth for the service version: pyproject reads it from here
# (hatchling `dynamic = ["version"]`), and so does `/version`. It lives in the
# package rather than in distribution metadata because the runtime image runs
# `uv sync --no-install-project` and copies the source in — nothing ever
# installs a distribution, so `importlib.metadata` cannot see this project.
__version__ = "2.2.0"
