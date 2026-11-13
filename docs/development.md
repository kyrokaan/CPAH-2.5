# Development

CPAH 2.0 supports Python 3.14 and Windows 10/11 x64. Dependencies are declared
with PEP 621 metadata in `pyproject.toml` and locked in `uv.lock`.

```powershell
python -m pip install uv
python -m uv sync --all-extras
python -m uv run pytest
python -m uv run ruff check cpah tests
python -m uv run mypy cpah
```

## Screenshot fixtures

`--analyze-screenshot PATH --json` is strictly read-only: it never searches for,
focuses, or sends input to a game window. Sanitized lossless fixtures should show
the entire game client and must not contain overlays or personal information.

English fixtures are the certified Cyberpunk 2.31 profile. Other bundled
languages are compatibility profiles and should not be promoted to certified
until their expected matrix, buffer, and objectives pass regression tests.

## Packaging

```powershell
python -m uv run pyinstaller cpah.spec
Get-FileHash dist\cpah.exe -Algorithm SHA256
```

The release artifact is a portable executable; no installer, CET, REDmod, or
game-directory changes are required.
