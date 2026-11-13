# CPAH 2.0

CPAH analyzes and solves Cyberpunk 2077 access-point and encrypted-shard Breach
Protocol puzzles. It is a standalone Windows application and does not modify the
game installation or save files.

## Compatibility

CPAH 2.0 targets Cyberpunk 2077 2.31. English is the primary detection profile;
the retained Arabic, German, Spanish, French, Italian, Japanese, Korean, Polish,
Portuguese, Russian, and Simplified Chinese profiles are best-effort.

The application recognizes the current Basic, Advanced, and Expert Datamine
objectives. Combat daemons are retained only as compatibility data for older
quest screenshots because enemy Breach Protocol no longer exists in game 2.x.

## Usage

1. Open an access point or encrypted shard and leave the full puzzle visible.
2. Press **Analyze** or the analysis hotkey (`Ctrl+Shift+H` by default).
3. Verify that CPAH's matrix, buffer, objectives, and path match the game.
4. Toggle objectives if the proposed path is longer than the buffer.
5. Press **Autohack** or its hotkey to send the configured navigation keys.

Automatic autohacking is opt-in and disabled by default. CPAH will not send any
input after incomplete or low-confidence detection. When Cyberpunk is running as
administrator, CPAH must run at the same integrity level for input to work.

Right-click **Analyze** to select a saved PNG/JPEG for read-only analysis. The
command-line equivalent is:

```powershell
cpah --analyze-screenshot puzzle.png --json
```

## Settings

- Detection language and thresholds control template matching.
- Buffer override is an escape hatch for unusual HUD rendering.
- Best-effort solving drops lower-value objectives in the order Basic,
  Advanced, Expert when all objectives cannot fit.
- Input delay can be increased for low-framerate systems.
- Window title is only a fallback; local games are discovered by
  `Cyberpunk2077.exe`.

GeForce NOW and AutoHotkey integration are not supported by CPAH 2.0.

See [Development](development.md) for source, testing, fixtures, and packaging.
