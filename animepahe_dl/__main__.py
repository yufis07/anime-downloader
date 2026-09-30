"""``python -m animepahe_dl`` launches the GUI; ``python -m animepahe_dl cli ...`` runs the CLI."""

import os
import sys


def _ensure_console() -> None:
    """The .exe is a windowed app; attach to the calling terminal so CLI output is visible."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    stream = None
    if sys.platform == "win32":
        try:
            import ctypes

            if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
                stream = open("CONOUT$", "w", encoding="utf-8", errors="replace")  # noqa: SIM115
        except Exception:  # noqa: BLE001
            stream = None
    if stream is None:
        stream = open(os.devnull, "w")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        _ensure_console()
        from .cli import main as cli_main

        return cli_main(sys.argv[2:])
    from .gui.app import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
