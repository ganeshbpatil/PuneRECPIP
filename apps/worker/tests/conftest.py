"""Shared across tests/unit and tests/integration."""

import os
from pathlib import Path

import pytest

# This sandbox ships a pre-installed Chromium at a path Playwright's own
# revision-matching `launch()` won't find automatically (see
# docs/modules/04-crawling.md) — used here if present and not overridden.
# A CI runner with no such path and a proper `playwright install chromium`
# step falls through to None, letting Playwright resolve its own managed
# browser as it would in any normal environment.
_SANDBOX_CHROMIUM_PATH = "/opt/pw-browsers/chromium"


@pytest.fixture(scope="session")
def chromium_executable_path() -> str | None:
    if "CHROMIUM_EXECUTABLE_PATH" in os.environ:
        return os.environ["CHROMIUM_EXECUTABLE_PATH"] or None
    if Path(_SANDBOX_CHROMIUM_PATH).exists():
        return _SANDBOX_CHROMIUM_PATH
    return None
