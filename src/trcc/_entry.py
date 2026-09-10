"""Shared CLI entry point — runs ``trcc`` (the new top-level tree).

Used by both invocations:

    python -m trcc        →  __main__.py  →  this _entry.main()
    trcc (console script) →  pyproject `trcc = "trcc._entry:main"`  →  this

The legacy tree (and its ``TRCC_LEGACY=1`` escape hatch) was moved to the
``legacy`` branch; this entry point dispatches straight to the new tree.
"""
from __future__ import annotations


def main() -> int | None:
    """Dispatch to the new top-level CLI, with startup crashes recorded.

    ``python -m trcc`` gets crash logging from ``__main__.py``.  The console
    script does NOT go through that file — ``[project.scripts]`` binds ``trcc``
    straight here — so until now every packaged install (rpm, deb, pacman,
    pipx, PyPI) had none.  Measured with a simulated import failure:
    ``python -m trcc`` wrote a log with the CRITICAL in it; ``trcc`` wrote
    nothing at all.

    Buffering here closes that, and costs one light import: the logging adapter
    pulls 7 trcc modules and no third-party package, ~6.6 ms.  Everything
    heavy — and every import that can realistically fail — happens on the line
    below, inside the guard.
    """
    import logging

    from trcc.adapters.infra.logging import ensure_configured, start_early_logging

    start_early_logging()
    log = logging.getLogger(__name__)
    log.info("main: dispatching to the CLI")
    try:
        from trcc.ui.cli.main import main as _next_main
        return _next_main()
    except Exception:
        log.critical("Fatal startup error", exc_info=True)
        try:
            ensure_configured()
        except Exception:
            log.exception("Fatal startup error: could not write the log either")
        raise
