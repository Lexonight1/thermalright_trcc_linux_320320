"""Logging coverage may only improve — the ratchet.

**Why this is enforced rather than remembered.**  Users diagnose through
``trcc report``, which pastes the log file.  For hardware we do not own that
paste IS the diagnosis, so a function with no log line is a bug report we
cannot answer.  The rule is therefore: *every function, new or old, gets a log
line* — and a rule nobody can fail is a rule that rots.

It cannot start green: 1451 of 3074 countable functions were silent when this
landed.  Failing on all of them would put CI permanently red, which is how a
gate gets ignored.  So it is a **ratchet**:

* add a silent function -> the count rises -> **fail**
* give a silent function a log line -> the count falls -> **fail**, asking you
  to lower :data:`MAX_SILENT` so the ground you gained cannot be lost

The number lives here, in the test, so every diff that moves it shows the
direction of travel.  It should only ever go down.

Exclusions are in ``dev/tools/logging_coverage.py`` and each has a cause:
abstract methods and stubs never ran, and dunders the logger invokes while
formatting a record (``__repr__``, ``__len__``, …) would recurse forever.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "dev" / "tools"))

import logging_coverage  # noqa: E402  # pyright: ignore[reportMissingImports]

#: Silent functions as of 2026-08-21 (landed at 1451; -5 by deleting six dead
#: functions, -7 by promoting eleven ``Platform`` members to ``@abstractmethod``
#: — an abstract method has no body, so it stops being countable, and the seven
#: silent ones among them stopped being excuses).  LOWER THIS as coverage
#: improves; never raise it.  Worst areas now:
#: ui 681, adapters 420, services 122, core 101.
#: 1344 -> 1343 on 2026-09-01: retiring ``SetDiskIndex`` deleted its silent
#: ``execute``.  A removal lowers this exactly as a fix does — the ratchet
#: asserts BOTH directions, so ground given back is a failure either way.
#: 1343 -> 1342 on 2026-09-02: ``DisconnectDevice.execute`` got the entry log
#: THE RULE requires, in the pass that gave it the shutdown blank.  It was the
#: one device-release path that reported nothing about why it did what it did.
#: 1342 -> 1341 the same day: ``ResetDevice.execute`` likewise, when it stopped
#: being a copy of DisconnectDevice and became a real disconnect-reconnect-
#: restore cycle whose three steps each need to be readable in a report.
#: 1341 -> 1340 on 2026-09-02: ``ListLedStyles.execute`` reported nothing while
#: it was telling users an 8-of-12 wrong answer, so the line names the zone
#: counts it resolved rather than that it ran.
#: 1340 -> 1339 the same day: ``TRCCApp._create_i18n_overlays`` builds the whole
#: About pane and the language picker and said nothing, so a report could not
#: show which language the labels were rendered in.
#: 1334 -> 1327 on 2026-09-08 with the video-export port.  Five came from
#: DELETING silent code rather than logging it: gui's hand-rolled
#: ``ExportWorker`` (its ``run``/``_do_export`` said nothing about an ffmpeg
#: failure) and qtgui's ``_ExportThread`` both went, replaced by one runner
#: whose every branch logs.  A duplicate implementation is silent twice.
#: The other two are the runner's own helpers, logged as they were written.
#: 1327 -> 1326 on 2026-09-08 with the video-export port (see above).
#: 1326 -> 1325 on 2026-09-09: the record-handling path joined the exemption
#: list, which removed ``__main__._SafeRotatingFileHandler.doRollover`` from
#: the countable set.  Nothing gained a log line — a function the rule could
#: never have been satisfied in stopped being counted, exactly as the
#: ``ClassContextFilter.filter`` entry did before it.  The ratchet asserts BOTH
#: directions, so this must come down with it.
#: 1325 -> 1324 the same day: ``_entry.main`` gained the entry log THE RULE
#: asks for, in the pass that gave the console script the startup-crash
#: buffering ``python -m trcc`` already had.  It was the one dispatch every
#: packaged install goes through, and it said nothing.
MAX_SILENT = 1324


def test_logging_coverage_only_improves() -> None:
    silent = logging_coverage.silent_functions()
    total = logging_coverage.countable_total()
    actual = len(silent)

    assert actual <= MAX_SILENT, (
        f"{actual - MAX_SILENT} new function(s) with no logging "
        f"({actual} silent of {total}).\n"
        f"Every function gets a log line — users diagnose through "
        f"`trcc report`, which pastes the log; a silent function is a bug "
        f"report we cannot answer.\n"
        f"List them:  PYTHONPATH=src python3 dev/tools/logging_coverage.py --list"
    )

    assert actual >= MAX_SILENT, (
        f"Logging coverage improved — {MAX_SILENT - actual} function(s) gained "
        f"a log line ({actual} silent of {total}).\n"
        f"Lower MAX_SILENT to {actual} in tests/test_logging_coverage.py so the "
        f"improvement cannot be lost."
    )


def test_recursion_risk_dunders_are_excluded_for_a_reason() -> None:
    """The exclusion list is a technical constraint, not a convenience.

    A log call inside ``__repr__`` recurses: the logger formats its arguments,
    which calls ``__repr__``, which logs.  Pinned so nobody 'tidies' the list
    into something arbitrary.
    """
    assert "__repr__" in logging_coverage._RECURSION_RISK
    assert "__len__" in logging_coverage._RECURSION_RISK
    # Things that are NOT recursion risks must not hide in there.
    for name in ("__init__", "__enter__", "__exit__", "__call__",
                 "__getitem__", "__init_subclass__"):
        assert name not in logging_coverage._RECURSION_RISK, (
            f"{name} is not invoked by log formatting — it must be counted"
        )


# =========================================================================
# The record-handling path — exempt because a log line there hangs the app
# =========================================================================


def _countable_names(src: str) -> set[str]:
    """Names the ratchet would demand a log line in, for a snippet."""
    import ast
    return {fn.name for fn in logging_coverage._countable(ast.parse(src))}


_A_LOGGING_HANDLER = '''
class SharedLogHandler(RenderOnceRotatingFileHandler):
    def __init__(self, filename, **kw):
        self._fd = os.open(str(filename) + ".lock", os.O_CREAT)
        super().__init__(filename, **kw)
    def emit(self, record):
        self._acquire(); super().emit(record)
    def shouldRollover(self, record):
        return os.stat(self.baseFilename).st_size > self.maxBytes
    def _open(self):
        stream = super()._open(); self._ino = 1; return stream
    def flush(self):
        super().flush()
    def doRollover(self):
        super().doRollover()
    def close(self):
        os.close(self._fd); super().close()
'''

#: The GUI's per-device handlers.  Their base name ENDS IN "Handler" but they
#: are not logging handlers, and the exemption must not reach them.
_A_GUI_DEVICE_HANDLER = '''
class LCDHandler(BaseHandler):
    def emit(self, frame):
        self._device.send(frame)
    def flush(self):
        self._queue.clear()
    def _open(self):
        self._device.connect()
    def format(self, theme):
        return theme.name.upper()
'''


def test_the_record_handling_path_is_exempt_on_a_logging_handler() -> None:
    """A log line in any of these recurses until the stack ends.

    Measured, entries provoked by ONE emitted record: emit 166, shouldRollover
    142, _open 409, flush 427.

    ``doRollover`` is exempt on a second, independent ground: it does NOT
    recurse (5 entries), but it runs under the cross-process rollover lock, and
    ``flock`` keeps no recursion count — take LOCK_EX twice on one fd, release
    once, and a peer process acquires.  A log line there re-enters ``emit``,
    whose ``finally`` drops the lock mid-rotation.

    ``close`` (1 entry) is off both paths, so THE RULE still applies to it.
    """
    countable = _countable_names(_A_LOGGING_HANDLER)

    for name in ("emit", "shouldRollover", "_open", "flush", "doRollover"):
        assert name not in countable, (
            f"{name} runs on the record-handling path or under the rollover "
            f"lock — a log line there hangs or corrupts rotation"
        )
    for name in ("__init__", "close"):
        assert name in countable, (
            f"{name} runs on neither path (measured), so it takes the log "
            f"line THE RULE requires"
        )


def test_the_exemption_does_not_reach_a_non_logging_handler() -> None:
    """``LCDHandler(BaseHandler)`` is a device handler, not a logging one.

    The qualifier used to be ``base.endswith("Handler")``, which these match.
    Nothing was wrongly exempt then, because neither declared any hook in the
    set — but widening it to ``_open`` / ``flush`` would have spent that luck
    silently, since both are ordinary methods on a device handler.
    """
    countable = _countable_names(_A_GUI_DEVICE_HANDLER)

    assert countable == {"emit", "flush", "_open", "format"}, (
        "the logging exemption leaked onto a non-logging class — every one of "
        "these is a real function that must carry a log line"
    )


def test_formatter_bases_are_matched_exactly_not_by_suffix() -> None:
    """A suffix test is what let the qualifier reach ``BaseHandler``."""
    assert "BaseHandler" not in logging_coverage._FORMATTER_BASES
    assert "Handler" in logging_coverage._FORMATTER_BASES
    assert "RenderOnceRotatingFileHandler" in logging_coverage._FORMATTER_BASES
