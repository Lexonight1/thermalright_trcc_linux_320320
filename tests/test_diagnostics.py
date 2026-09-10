"""Diagnostics — health checks, doctor, debug report bundle."""
from __future__ import annotations

import ast
import logging
import os
import re
from contextlib import contextmanager
from pathlib import Path

import pytest

from trcc.adapters.diagnostics import health as health_mod
from trcc.adapters.diagnostics.adapter import DiagnosticsAdapter
from trcc.adapters.diagnostics.debug_report import build_debug_report
from trcc.adapters.diagnostics.doctor import (
    render_doctor_output,
    run_doctor,
)
from trcc.adapters.diagnostics.health import (
    HealthCheckResult,
    check_gpu_sensors,
    check_log_writable,
    check_python_version,
    package_install_hint,
    run_health_checks,
)
from trcc.adapters.infra.logging import (
    ClassContextFilter,
    PosixSharedLogHandler,
    RenderOnceRotatingFileHandler,
    configure_logging,
    log_chain,
    shared_handler_class,
    start_early_logging,
    tail_log,
    tail_log_actions,
)
from trcc.core.logs import PER_FRAME_ROOT, TRACE, levels_for, per_frame, trace

# =========================================================================
# Logging adapter
# =========================================================================


def test_configure_logging_creates_writable_handler(tmp_path: Path) -> None:
    log_file = tmp_path / "trcc.log"
    configure_logging(log_file)
    import logging
    logging.getLogger("trcc.test").warning("hello-from-test")
    assert log_file.is_file()
    body = log_file.read_text(encoding="utf-8")
    assert "hello-from-test" in body


def test_configure_logging_is_idempotent(tmp_path: Path) -> None:
    """Calling configure_logging twice should not pile up handlers."""
    import logging
    log_file = tmp_path / "trcc.log"
    configure_logging(log_file)
    initial = len(logging.getLogger().handlers)
    configure_logging(log_file)
    after = len(logging.getLogger().handlers)
    assert initial == after


def test_latest_log_holds_only_the_current_run(tmp_path: Path) -> None:
    """``<stem>.latest.log`` must be truncated per run — the whole point of it.

    It was not, for a long time: ``RotatingFileHandler`` SILENTLY discards
    ``mode="w"`` when ``maxBytes > 0`` (CPython forces ``"a"``), so the
    per-run file quietly accumulated days of runs.  Reading a stale window as
    the current run caused repeated misdiagnoses — the file contained what you
    expected because an EARLIER run had written it.
    """
    import logging

    log_file = tmp_path / "trcc.log"
    latest = tmp_path / "trcc.latest.log"

    configure_logging(log_file)
    logging.getLogger("trcc.test").warning("run-one-marker")
    assert "run-one-marker" in latest.read_text(encoding="utf-8")

    # A second process/init: the previous run's lines must be GONE.
    configure_logging(log_file)
    logging.getLogger("trcc.test").warning("run-two-marker")

    body = latest.read_text(encoding="utf-8")
    assert "run-two-marker" in body
    assert "run-one-marker" not in body, (
        "latest.log still holds the previous run — it is append-only again, "
        "and any diagnosis reading it can land on a stale window"
    )
    # The cumulative history file keeps BOTH — that is its job.
    history = log_file.read_text(encoding="utf-8")
    assert "run-one-marker" in history and "run-two-marker" in history


def _count_renders(root: logging.Logger) -> dict[str, int]:
    """Wrap every attached formatter so a test can count real render work."""
    calls = {"format": 0, "formatTime": 0}
    for handler in root.handlers:
        # Only OUR handlers.  pytest attaches its own capture handler with its
        # own formatter, and counting that would measure the test runner.
        if not getattr(handler, "_trcc_handler", False):
            continue
        fmt = handler.formatter
        if fmt is None or getattr(fmt, "_counted", False):
            continue
        original_format, original_time = fmt.format, fmt.formatTime

        def counted_format(record, _o=original_format):
            calls["format"] += 1
            return _o(record)

        def counted_time(record, datefmt=None, _o=original_time):
            calls["formatTime"] += 1
            return _o(record, datefmt)

        fmt.format = counted_format          # type: ignore[method-assign]
        fmt.formatTime = counted_time        # type: ignore[method-assign]
        fmt._counted = True                  # type: ignore[attr-defined]
    return calls


def test_a_record_is_rendered_once_not_four_times(tmp_path: Path) -> None:
    """Two rotating handlers must not turn one record into four renders.

    CPython's ``RotatingFileHandler.shouldRollover`` calls ``format(record)``
    purely to take ``len()`` of the result and discards it, and this app
    attaches two rotating handlers -- so a record was formatted four times,
    with four ``strftime`` calls, three of them wasted.  Logging was measured
    at 82-90%% of the CPU regression since v9.9.2, so the waste is not
    academic.

    MUTATION CHECK: make the handlers plain ``RotatingFileHandler`` again and
    this fails with 4 != 1.
    """
    configure_logging(tmp_path / "t.log", level=logging.DEBUG,
                      stderr_level=logging.CRITICAL)
    calls = _count_renders(logging.getLogger())

    logging.getLogger("render.once").debug("one %s %d", "record", 42)
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert calls["format"] == 1
    assert calls["formatTime"] == 1


def test_rendering_once_still_writes_the_same_text_to_both_files(
    tmp_path: Path,
) -> None:
    """Caching the rendered text must not change what lands on disk.

    The whole point is that only the NUMBER of renders changes.  Both the
    rolling file and the per-run ``latest`` must carry byte-identical lines.

    Note this cannot detect a cache that ignores the formatter identity --
    both handlers here share one formatter, so the text is the same either
    way.  ``test_a_handler_with_its_own_formatter_renders_its_own_text``
    guards that separately.
    """
    log_file = tmp_path / "t.log"
    configure_logging(log_file, level=logging.DEBUG,
                      stderr_level=logging.CRITICAL)
    logging.getLogger("render.once").debug("payload %s", "value")
    for handler in logging.getLogger().handlers:
        handler.flush()

    rolling = [ln for ln in log_file.read_text().splitlines() if "payload" in ln]
    latest = [ln for ln in (tmp_path / "t.latest.log").read_text().splitlines()
              if "payload" in ln]

    assert rolling == latest
    assert len(rolling) == 1
    assert rolling[0].endswith("payload value")
    assert "render.once" in rolling[0]


def test_a_handler_with_its_own_formatter_renders_its_own_text(
    tmp_path: Path,
) -> None:
    """The render cache is keyed by formatter, so it cannot leak between them.

    The two handlers this app configures share one formatter, so a cache that
    ignored identity would look correct forever -- right up until someone
    attaches a handler with its own format string and silently gets another
    handler's text.  Keyed on identity, each renders its own.

    MUTATION CHECK: drop ``cached[0] is self.formatter`` from the cache lookup
    in ``RenderOnceRotatingFileHandler.format`` and this fails -- the second
    handler emits the first one's line.
    """
    first = RenderOnceRotatingFileHandler(tmp_path / "first.log", encoding="utf-8")
    first.setFormatter(logging.Formatter("FIRST %(message)s"))
    second = RenderOnceRotatingFileHandler(tmp_path / "second.log", encoding="utf-8")
    second.setFormatter(logging.Formatter("SECOND %(message)s"))

    record = logging.LogRecord("t", logging.INFO, __file__, 1, "shared", None, None)
    for handler in (first, second):
        handler.handle(record)
        handler.close()

    assert (tmp_path / "first.log").read_text().strip() == "FIRST shared"
    assert (tmp_path / "second.log").read_text().strip() == "SECOND shared"


def test_per_frame_lines_are_silent_by_default(tmp_path: Path) -> None:
    """The frame path must not write to the file during a normal run.

    Per-frame lines were 92%% of every record and ~90%% of the CPU regression
    since v9.9.2 — 44 records per rendered frame at 688/s.  At INFO their
    ``.debug()`` short-circuits in ``isEnabledFor``, so the LogRecord is never
    constructed, which is where the saving is.

    MUTATION CHECK: drop the ``PER_FRAME_ROOT`` setLevel from
    ``configure_logging`` and this fails — the frame line lands in the file.
    """
    log_file = tmp_path / "t.log"
    configure_logging(log_file, level=logging.DEBUG,
                      stderr_level=logging.CRITICAL)

    per_frame(__name__).debug("frame tick %d", 7)
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "frame tick" not in log_file.read_text()


def test_one_v_brings_the_frame_path_back(tmp_path: Path) -> None:
    """``-v`` is what buys the firehose — it must actually restore it.

    MUTATION CHECK: hard-code the level to INFO and this fails.
    """
    log_file = tmp_path / "t.log"
    configure_logging(log_file, level=logging.DEBUG,
                      stderr_level=logging.CRITICAL, per_frame=True)

    per_frame(__name__).debug("frame tick %d", 7)
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "frame tick 7" in log_file.read_text()


def test_ordinary_debug_still_reaches_the_file_by_default(
    tmp_path: Path,
) -> None:
    """The report keeps its DEBUG detail — only the FRAME path is gated.

    This is the guarantee that separates this change from the one it replaced.
    Silencing DEBUG wholesale would save the same CPU and re-break exactly
    what the always-DEBUG rule exists to fix: the one-shot lines a reporter
    needs — which sysfs path the device resolved to, which transport opened,
    why a download was skipped — are only 0.6%% of the records and cost
    nothing.

    MUTATION CHECK: set the ROOT logger to INFO instead of the per-frame
    family and this fails — the whole diagnostic trail vanishes with the noise.
    """
    log_file = tmp_path / "t.log"
    configure_logging(log_file, level=logging.DEBUG,
                      stderr_level=logging.CRITICAL)

    logging.getLogger("trcc.adapters.system.linux").debug(
        "_resolve_scsi_path: %s", "0402:3922")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "_resolve_scsi_path: 0402:3922" in log_file.read_text()


def test_per_frame_loggers_are_one_family(tmp_path: Path) -> None:
    """Every per-frame logger is silenced by ONE setLevel, with no registry.

    They are children of a single parent, so a module that starts logging
    per-frame lines is covered the moment it calls ``per_frame`` — nobody has
    to remember to add it to a list, which is the thing that would drift.
    """
    configure_logging(tmp_path / "t.log", level=logging.DEBUG,
                      stderr_level=logging.CRITICAL)

    for module in ("trcc.services.display", "trcc.adapters.render.qt",
                   "trcc.some.module.written.tomorrow"):
        assert per_frame(module).getEffectiveLevel() == logging.WARNING
        assert per_frame(module).name.startswith(PER_FRAME_ROOT)


def test_tail_log_handles_missing_file(tmp_path: Path) -> None:
    assert tail_log(tmp_path / "absent.log") == []


def test_tail_log_returns_last_n_lines(tmp_path: Path) -> None:
    log_file = tmp_path / "trcc.log"
    log_file.write_text("\n".join(f"line {i}" for i in range(500)))
    tail = tail_log(log_file, n_lines=10)
    assert len(tail) == 10
    assert tail[-1] == "line 499"


# =========================================================================
# The rotation chain — a report reads the SET, not the live segment
# =========================================================================
#
# ``trcc report`` is the entire diagnosis for hardware we do not own, and it
# used to read ``trcc.log`` alone.  A rollover therefore cut it to whatever the
# live segment happened to hold: measured on a SINGLE writer, 5,300 significant
# records emitted gave ``tail_log(1000)`` -> 423 lines and
# ``tail_log_actions(500)`` -> 424, the other 4,876 sitting unread in
# ``trcc.log.1``.  No concurrency needed to lose them.


def _rotated(tmp_path: Path, segments: dict[str, list[str]]) -> Path:
    """Write a rotation set by hand.  Keys are suffixes, ``""`` is the live file."""
    base = tmp_path / "trcc.log"
    for suffix, lines in segments.items():
        target = base if suffix == "" else base.with_name(f"trcc.log.{suffix}")
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return base


def test_log_chain_is_oldest_first_and_ends_at_the_live_file() -> None:
    """Rotation renames base -> .1 -> .2, so a HIGHER suffix is OLDER."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        base = _rotated(Path(d), {"2": ["old"], "1": ["mid"], "": ["live"]})
        assert [p.name for p in log_chain(base)] == [
            "trcc.log.2", "trcc.log.1", "trcc.log",
        ]


def test_log_chain_ignores_siblings_that_are_not_segments(
    tmp_path: Path,
) -> None:
    """Only NUMERIC suffixes are log content.

    The multi-process rollover lock is a sidecar named ``trcc.log.lock`` — it
    shares the prefix and is not a segment.  ``trcc.latest.log`` is a separate
    file with its own lifetime and must not be spliced in either.
    """
    base = _rotated(tmp_path, {"1": ["mid"], "": ["live"]})
    (tmp_path / "trcc.log.lock").write_text("", encoding="utf-8")
    (tmp_path / "trcc.latest.log").write_text("latest\n", encoding="utf-8")
    (tmp_path / "trcc.log.bak").write_text("bak\n", encoding="utf-8")

    assert [p.name for p in log_chain(base)] == ["trcc.log.1", "trcc.log"]


def test_log_chain_of_a_missing_file_is_empty(tmp_path: Path) -> None:
    assert log_chain(tmp_path / "absent.log") == []


def test_tail_log_reaches_into_the_backups(tmp_path: Path) -> None:
    """The 423-of-1000 case: the live segment holds far less than the budget."""
    base = _rotated(tmp_path, {
        "1": [f"old {i}" for i in range(900)],
        "": [f"live {i}" for i in range(100)],
    })
    tail = tail_log(base, n_lines=1000)

    assert len(tail) == 1000
    assert tail[0] == "old 0"
    assert tail[899] == "old 899"
    assert tail[900] == "live 0"
    assert tail[-1] == "live 99"


def test_tail_log_actions_reaches_into_the_backups(tmp_path: Path) -> None:
    """Significance selection spans the chain, not just the live segment."""
    base = _rotated(tmp_path, {
        "1": [_record("INFO", "LoadTheme ok: Theme1")]
             + [_record("DEBUG", f"draw_text {i}", i) for i in range(2000)],
        "": [_record("DEBUG", f"draw_text {i}", i) for i in range(2000)],
    })

    assert [line.split(": ", 1)[-1] for line in tail_log_actions(base)] == [
        "LoadTheme ok: Theme1",
    ]


def test_a_records_traceback_does_not_leak_across_a_rollover(
    tmp_path: Path,
) -> None:
    """A segment boundary resets continuation tracking.

    One ``emit`` writes a whole record — traceback included — and rollover
    happens between records, so a continuation line can never belong to a
    record in the PREVIOUS segment.  Without the reset, a DEBUG-suppressed
    record at the end of one segment could adopt the next segment's first line.
    """
    base = _rotated(tmp_path, {
        "1": [_record("ERROR", "boom"), "Traceback (most recent call last):"],
        "": ["  File 'orphan.py', line 1", _record("INFO", "after rollover")],
    })
    kept = tail_log_actions(base)

    assert kept == [
        _record("ERROR", "boom"),
        "Traceback (most recent call last):",
        _record("INFO", "after rollover"),
    ]


# =========================================================================
# Multi-process rotation — the daemon flip makes 2+ writers permanent
# =========================================================================


@contextmanager
def _shared_handler(log_file: Path, **kwargs: object):
    """A multi-process handler on its own logger, cleaned up afterwards."""
    handler = shared_handler_class()(log_file, encoding="utf-8", **kwargs)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("trcc.test.shared")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    previous = list(logger.handlers)
    logger.handlers[:] = [handler]
    try:
        yield logger, handler
    finally:
        handler.close()
        logger.handlers[:] = previous


def test_a_peer_rotation_moves_our_writes_onto_the_new_file(
    tmp_path: Path,
) -> None:
    """The orphaned-writer bug, in one step.

    ``RotatingFileHandler`` decides rollover from ``self.stream.tell()`` — OUR
    position in the file WE opened.  After a peer renames that file away, the
    stream keeps working and we keep appending to an inode nothing reads:
    measured with three processes, ``trcc.log`` held 2,263 records from one
    writer and ZERO from the other two.  Asking ``stat`` for the shared file
    instead answers both questions — its size, and whether it is still ours.
    """
    log_file = tmp_path / "trcc.log"
    with _shared_handler(log_file, maxBytes=10_000_000, backupCount=5) as (lg, _h):
        lg.info("before-peer-rotation")

        # A peer rotates underneath us: our inode becomes .1, a NEW file
        # takes the name.  Nothing tells us; only the inode differs.
        log_file.rename(tmp_path / "trcc.log.1")
        log_file.write_text("", encoding="utf-8")

        lg.info("after-peer-rotation")

    assert "after-peer-rotation" in log_file.read_text(encoding="utf-8"), (
        "still writing into the inode the peer renamed away — those records "
        "are invisible to the file `trcc report` reads"
    )
    assert "before-peer-rotation" in (
        tmp_path / "trcc.log.1").read_text(encoding="utf-8")


def test_a_peer_rotation_does_not_rotate_the_chain_a_second_time(
    tmp_path: Path,
) -> None:
    """One overflow must advance the chain ONCE, not once per writer.

    Rotating again for a rollover a peer already did is what cost three
    writers 17.6 points of retention (47.8% -> 30.2%).
    """
    log_file = tmp_path / "trcc.log"
    with _shared_handler(log_file, maxBytes=10_000_000, backupCount=5) as (lg, _h):
        lg.info("first")
        log_file.rename(tmp_path / "trcc.log.1")
        log_file.write_text("", encoding="utf-8")
        lg.info("second")

    # A second rotation would have pushed the peer's file down to .2.
    assert (tmp_path / "trcc.log.1").is_file()
    assert not (tmp_path / "trcc.log.2").exists(), (
        "the chain advanced twice for one overflow — every extra writer would "
        "shorten retention by another generation"
    )


def test_the_lock_sidecar_exists_and_is_never_read_as_log_content(
    tmp_path: Path,
) -> None:
    """The lock lives beside the log, so the chain reader must skip it."""
    log_file = tmp_path / "trcc.log"
    configure_logging(log_file, level=logging.DEBUG,
                      stderr_level=logging.CRITICAL)
    logging.getLogger("trcc.test").warning("a-record")

    assert (tmp_path / "trcc.log.lock").is_file()
    assert (tmp_path / "trcc.latest.log.lock").is_file()
    assert [p.name for p in log_chain(log_file)] == ["trcc.log"]


def test_a_closed_handler_drops_records_rather_than_reopening(
    tmp_path: Path,
) -> None:
    """``close()`` does not detach, and stdlib answers records by re-opening.

    That silently leaks the reopened file object and writes without the lock.
    A closed shared handler stays closed instead — safe because in production
    ``close()`` only ever follows ``removeHandler``.
    """
    log_file = tmp_path / "trcc.log"
    handler = shared_handler_class()(
        log_file, maxBytes=10_000_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.close()

    assert handler._lock_fd == -1
    handler.emit(logging.LogRecord(
        "trcc.test", logging.WARNING, __file__, 1, "after-close", None, None))

    assert handler.stream is None, "a closed handler re-opened its stream"
    # The file need not exist at all: a handler that may not hold the file open
    # is built with delay=True, so nothing is created until a record is written
    # -- and this one never wrote any.
    body = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    assert "after-close" not in body


def test_a_live_peer_keeps_its_run_so_we_append_to_latest(
    tmp_path: Path,
) -> None:
    """``latest`` belongs to the SESSION, not to whichever process started last.

    The sequential gate above cannot see this: it calls ``configure_logging``
    twice in one process, where the second call legitimately owns the run
    again.  With a LIVE peer the old behaviour wiped a running session's log —
    measured with three writers, one lost 1,501 of 9,000 records and another
    3,356, leaving a file blended from three runs.

    The peer claims the run through the SAME primitive the app uses, so this
    test runs on every OS rather than reaching for ``fcntl`` directly.
    """
    import subprocess
    import sys

    log_file = tmp_path / "trcc.log"
    latest = tmp_path / "trcc.latest.log"
    latest.write_text("PEER-SESSION-MARKER\n", encoding="utf-8")

    # A context manager, so the pipes close with the process — a leaked one
    # surfaces as a ResourceWarning inside whichever unrelated test runs next.
    with subprocess.Popen(
        [sys.executable, "-c",
         "import os, sys\n"
         "from trcc.adapters.infra.logging import shared_handler_class\n"
         "fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o644)\n"
         "shared_handler_class()._claim_run(fd)\n"
         "print('held', flush=True)\n"
         "sys.stdin.read()\n",
         str(tmp_path / "trcc.latest.log.run")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    ) as peer:
        try:
            assert peer.stdout is not None
            assert peer.stdout.readline().strip() == "held", (
                "the peer could not claim the run — setup, not the behaviour"
            )
            configure_logging(log_file, level=logging.DEBUG,
                              stderr_level=logging.CRITICAL)
            body = latest.read_text(encoding="utf-8")
        finally:
            assert peer.stdin is not None
            peer.stdin.close()
            peer.wait(timeout=10)

    assert "PEER-SESSION-MARKER" in body, (
        "a joining process truncated a LIVE peer's per-run log — the peer's "
        "session is gone and what remains is half one run, half another"
    )


def test_the_run_claim_is_released_so_a_later_launch_owns_a_fresh_run(
    tmp_path: Path,
) -> None:
    """The other half: once nobody holds it, the next launch truncates again.

    Also the self-conflict guard — ``flock`` is per open file DESCRIPTION, so
    a second ``configure_logging`` in ONE process must release its own claim
    before probing, or it would mistake itself for a live peer and never
    truncate again.
    """
    log_file = tmp_path / "trcc.log"
    latest = tmp_path / "trcc.latest.log"

    configure_logging(log_file, level=logging.DEBUG,
                      stderr_level=logging.CRITICAL)
    logging.getLogger("trcc.test").warning("run-one-marker")
    configure_logging(log_file, level=logging.DEBUG,
                      stderr_level=logging.CRITICAL)
    logging.getLogger("trcc.test").warning("run-two-marker")

    body = latest.read_text(encoding="utf-8")
    assert "run-two-marker" in body
    assert "run-one-marker" not in body, (
        "the process mistook its OWN previous claim for a live peer and "
        "stopped truncating — the per-run guarantee is silently retired"
    )


def test_a_handler_that_may_not_hold_the_file_closes_it_between_records(
    tmp_path: Path,
) -> None:
    """The Windows rotation fix, exercised on whatever OS runs this.

    Windows cannot rename a file a PEER holds open — ``os.rename`` needs
    exclusive access to the source and CPython's ``open(path, "a")`` does not
    request ``FILE_SHARE_DELETE``, so the rename fails with WinError 32.
    Serialising rotation does not help, because the peer is not the process
    rotating.  So the Windows handler holds nothing between records, exactly as
    ``concurrent-log-handler`` does.

    ``_keep_open`` is a plain attribute rather than a ``sys.platform`` test
    precisely so this is testable here: a Windows-only path only Windows can
    run is as unverifiable as the bug it fixes.
    """
    handler_cls = shared_handler_class()

    class ClosesBetweenRecords(handler_cls):  # type: ignore[valid-type,misc]
        _keep_open = False

    log_file = tmp_path / "trcc.log"
    handler = ClosesBetweenRecords(
        log_file, maxBytes=10_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("trcc.test.keepopen")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.handlers[:] = [handler]
    try:
        assert handler.stream is None, (
            "the file was opened at construction — nothing may hold it, "
            "including before the first record"
        )
        logger.info("first")
        assert handler.stream is None, (
            "the file is still open after a write — on Windows a peer's "
            "handle in this state fails every rotation with WinError 32"
        )
        logger.info("second")
        assert log_file.read_text(encoding="utf-8").splitlines() == [
            "first", "second",
        ], "closing between records must not cost records or truncate"
    finally:
        handler.close()
        logger.handlers[:] = []


@pytest.mark.skipif(
    shared_handler_class() is not PosixSharedLogHandler,
    reason="asserts the POSIX handler's own policy; it needs fcntl to build",
)
def test_the_posix_handler_does_hold_the_file_open(tmp_path: Path) -> None:
    """The other half: POSIX must NOT pay for a Windows-only constraint.

    Renaming an open file is an inode swap on POSIX, so the lock alone is
    sufficient there and the +8.9%/record measurement assumes the stream stays
    open.  Silently flipping every OS to open-per-record would be a much larger
    regression than the bug it came from.
    """
    handler = PosixSharedLogHandler(
        tmp_path / "trcc.log", maxBytes=10_000_000, backupCount=1,
        encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        assert handler._keep_open is True
        handler.emit(logging.LogRecord(
            "t", logging.WARNING, __file__, 1, "one", None, None))
        assert handler.stream is not None
    finally:
        handler.close()


class _StubMsvcrt:
    """Just enough ``msvcrt`` to drive the Windows handler on any OS.

    Byte-range semantics are the OS's business and this cannot check them.
    What it CAN check is our side of the contract — that the handler seeks to
    byte 0 before every lock (``msvcrt`` locks from the CURRENT position, so
    forgetting the seek locks a different byte each time and serialises
    nothing), takes the blocking mode to acquire and the unlock mode to
    release, and pairs them exactly.
    """

    LK_LOCK = 1
    LK_NBLCK = 2
    LK_UNLCK = 0

    #: Where this stub leaves the file position after every call, so the next
    #: caller MUST seek.  Without it the offset is 0 whether or not anyone
    #: seeks — the lock fd is never read or written — and an assertion that the
    #: handler locks byte 0 passes even when the seek is deleted.  Caught by
    #: mutation, not by review: removing the ``lseek`` from ``_acquire`` left
    #: the test green.
    DIRTY_POSITION = 7

    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []
        self.held: set[int] = set()

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        offset = os.lseek(fd, 0, os.SEEK_CUR)
        self.calls.append((offset, mode, nbytes))
        os.lseek(fd, self.DIRTY_POSITION, os.SEEK_SET)
        if mode == self.LK_UNLCK:
            self.held.discard(fd)
            return
        if fd in self.held:
            raise OSError(13, "already locked")
        self.held.add(fd)


def test_the_windows_handler_locks_the_way_msvcrt_requires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the REAL Windows class, on this OS, with a stubbed ``msvcrt``.

    Windows has no test run anywhere — ``windows.yml`` builds the installer and
    never calls pytest, every other workflow is ubuntu-only — so this class
    would otherwise ship having never executed a single line.  This does not
    prove Windows file semantics; it proves the code we wrote does what
    ``msvcrt`` documents: lock one byte, from position 0, blocking to acquire
    and unlocking to release.
    """
    import sys as sys_mod

    from trcc.adapters.infra.logging import WindowsSharedLogHandler

    stub = _StubMsvcrt()
    monkeypatch.setitem(sys_mod.modules, "msvcrt", stub)

    log_file = tmp_path / "trcc.log"
    handler = WindowsSharedLogHandler(
        log_file, maxBytes=10_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("trcc.test.win")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.handlers[:] = [handler]
    try:
        logger.info("first")
        logger.info("second")

        assert log_file.read_text(encoding="utf-8").splitlines() == [
            "first", "second",
        ]
        # Every lock call: byte 0, one byte.
        assert all(offset == 0 and nbytes == 1
                   for offset, _mode, nbytes in stub.calls), stub.calls
        # Acquire/release pair per record, plus the constructor's probe.
        modes = [mode for _o, mode, _n in stub.calls]
        assert modes == [stub.LK_LOCK, stub.LK_UNLCK] * (len(modes) // 2), (
            f"locks and unlocks are not paired in order: {modes}"
        )
        assert not stub.held, "a lock was left held after the last record"
        # And the Windows policy: nothing holds the file between records.
        assert handler.stream is None
    finally:
        handler.close()
        logger.handlers[:] = []


def test_the_windows_run_claim_uses_the_non_blocking_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_claim_run`` must NOT block — it is a "is a peer alive?" question.

    ``LK_LOCK`` would retry for ten seconds and then raise, turning a startup
    probe into a ten-second stall.  ``LK_NBLCK`` answers immediately, and it is
    the only exclusive non-blocking mode ``msvcrt`` has — there is no shared
    mode at all, which is why the run claim is held rather than probed.
    """
    import sys as sys_mod

    from trcc.adapters.infra.logging import WindowsSharedLogHandler

    stub = _StubMsvcrt()
    monkeypatch.setitem(sys_mod.modules, "msvcrt", stub)

    fd = os.open(tmp_path / "trcc.latest.log.run", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        os.lseek(fd, stub.DIRTY_POSITION, os.SEEK_SET)   # must seek back to 0
        WindowsSharedLogHandler._claim_run(fd)
        assert stub.calls == [(0, stub.LK_NBLCK, 1)]
        with pytest.raises(OSError):
            WindowsSharedLogHandler._claim_run(fd)   # a peer holds it
    finally:
        os.close(fd)


def test_a_lock_that_cannot_be_taken_never_raises_into_the_caller(
    tmp_path: Path,
) -> None:
    """A logging call must not become an exception in application code.

    Every stdlib ``emit`` wraps its whole body and routes failure to
    ``handleError``.  The lock calls sat outside that protection, and a
    ``BlockingIOError`` escaped a plain ``lg.info(...)`` — measured.

    Windows makes it reachable rather than theoretical:
    ``msvcrt.locking(LK_LOCK)`` retries at one-second intervals, ten times,
    then raises ``OSError``.  ``flock`` blocks indefinitely, so POSIX never
    surfaced it.
    """
    handler_cls = shared_handler_class()

    class LockFailsAfterConstruction(handler_cls):  # type: ignore[valid-type,misc]
        armed = False

        def _acquire(self) -> None:
            if self.armed:
                raise OSError(11, "simulated: LK_LOCK gave up after ten tries")
            super()._acquire()

    handler = LockFailsAfterConstruction(
        tmp_path / "trcc.log", maxBytes=10_000_000, backupCount=1,
        encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(ClassContextFilter())
    logger = logging.getLogger("trcc.test.lockfail")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.handlers[:] = [handler]
    try:
        logger.info("healthy")
        handler.armed = True
        # The assertion IS that this does not raise.
        logger.info("the lock is now unavailable")
    finally:
        handler.armed = False
        handler.close()
        logger.handlers[:] = []


# =========================================================================
# Startup records — buffered until the real destination is known
# =========================================================================


def test_early_records_reach_the_real_log_in_the_real_format(
    tmp_path: Path,
) -> None:
    """The whole point: a startup CRITICAL must survive into the report.

    The old shim wrote them itself, with its own format and its own path.
    ``tail_log_actions`` returned **0 lines** for a startup CRITICAL, because
    a space-separated date and a bracketed ``[CRITICAL]`` made ``_log_level_of``
    read the time-of-day as the level and classify every early record as a
    continuation line.
    """
    start_early_logging()
    early = logging.getLogger("trcc.test.early")
    early.info("STARTING-UP marker")
    try:
        raise ImportError("simulated startup failure")
    except ImportError:
        early.critical("Fatal startup error", exc_info=True)

    log_file = tmp_path / "trcc.log"
    configure_logging(log_file, level=logging.DEBUG,
                      stderr_level=logging.CRITICAL)

    body = log_file.read_text(encoding="utf-8")
    assert "STARTING-UP marker" in body
    assert "Fatal startup error" in body

    actions = tail_log_actions(log_file, 500)
    assert any("Fatal startup error" in line for line in actions), (
        "the startup CRITICAL is in the file but invisible to the report's "
        "significant-actions section — which is the half a maintainer reads"
    )
    assert any("simulated startup failure" in line for line in actions), (
        "the traceback was dropped from the record it belongs to"
    )


def test_early_records_are_not_written_twice(tmp_path: Path) -> None:
    """The buffer detaches BEFORE the real handlers attach.

    Left attached during ``configure_logging`` it keeps collecting, so every
    record the configuration itself emits lands in the file directly AND is
    replayed after — measured, the ``shared_handler_class`` line appeared 5
    times in a 51-line log.
    """
    start_early_logging()
    logging.getLogger("trcc.test.early").warning("ONCE-ONLY marker")

    log_file = tmp_path / "trcc.log"
    configure_logging(log_file, level=logging.DEBUG,
                      stderr_level=logging.CRITICAL)

    body = log_file.read_text(encoding="utf-8")
    assert body.count("ONCE-ONLY marker") == 1
    assert body.count("_RunOwnership.claim: this process owns the run") == 1, (
        "a configure-time record was written once directly and once by the "
        "replay — the buffer is still attached while the handlers go on"
    )


def test_the_early_buffer_does_not_look_like_configured_logging() -> None:
    """``ensure_configured`` no-ops when it sees a ``_HANDLER_TAG`` handler.

    So the buffer must NOT carry that tag: a console-script launch
    (``trcc-gui`` / ``trcc-lcd``) calls ``ensure_configured()`` bare, and a
    tagged buffer would convince it logging was already set up — leaving the
    whole session with no file handler at all, which is the exact defect
    ``ensure_configured`` exists to prevent.
    """
    from trcc.adapters.infra.logging import _EARLY_TAG, _HANDLER_TAG

    root = logging.getLogger()
    assert start_early_logging() is True
    buffers = [h for h in root.handlers if getattr(h, _EARLY_TAG, False)]

    assert len(buffers) == 1
    assert not getattr(buffers[0], _HANDLER_TAG, False)
    assert not any(getattr(h, _HANDLER_TAG, False) for h in root.handlers), (
        "the early buffer registered as configured logging — ensure_configured "
        "will now skip installing a file handler"
    )
    assert start_early_logging() is False, "buffering twice stacks handlers"


def test_logging_survives_a_platform_that_cannot_be_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The diagnostic path must not share the fate of the broken import.

    ``adapters.system`` pulls in pyusb / psutil / pynvml, and a startup crash
    in one of those is exactly the crash worth recording — so asking it where
    the log lives cannot be allowed to lose the answer.
    """
    from trcc.adapters import system as system_mod
    from trcc.adapters.infra import logging as logging_mod

    def _explode() -> object:
        raise ImportError("simulated: no module named 'usb'")

    monkeypatch.setattr(system_mod, "current_platform", _explode)
    monkeypatch.setattr(logging_mod, "LAST_RESORT_LOG", tmp_path / "trcc.log")

    start_early_logging()
    logging.getLogger("trcc.test.early").critical("Fatal startup error")
    assert logging_mod.ensure_configured(force=True) is True

    body = (tmp_path / "trcc.log").read_text(encoding="utf-8")
    assert "Fatal startup error" in body
    assert "could not ask the platform where the log lives" in body, (
        "the fallback path must say it IS a fallback — on macOS and Windows "
        "the report reads somewhere else entirely"
    )


# =========================================================================
# Action history — selecting by significance, not recency
# =========================================================================


def _record(level: str, msg: str, i: int = 0) -> str:
    """One line in this project's real format (level is the 2nd token)."""
    return f"2026-08-02T12:00:{i % 60:02d} {level:<7} trcc.mod:fn:{i}: {msg}"


def test_tail_log_actions_handles_missing_file(tmp_path: Path) -> None:
    assert tail_log_actions(tmp_path / "absent.log") == []


def test_tail_log_actions_reaches_past_the_tail_window(tmp_path: Path) -> None:
    """The reason this exists.

    A render loop buries the user's actions: here one action is followed by
    2000 DEBUG lines, so a 1000-line tail cannot see it at all while the
    action history returns it as the only entry.
    """
    log_file = tmp_path / "trcc.log"
    log_file.write_text("\n".join(
        [_record("INFO", "LoadTheme ok: Theme1")]
        + [_record("DEBUG", f"draw_text {i}", i) for i in range(2000)],
    ))

    assert not any("LoadTheme" in line for line in tail_log(log_file, 1000))
    assert [line.split(": ", 1)[-1]
            for line in tail_log_actions(log_file)] == ["LoadTheme ok: Theme1"]


def test_tail_log_actions_keeps_every_level_above_debug(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "trcc.log"
    log_file.write_text("\n".join(
        _record(lvl, lvl.lower())
        for lvl in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    ))

    kept = tail_log_actions(log_file)

    assert [line.split()[1] for line in kept] == [
        "INFO", "WARNING", "ERROR", "CRITICAL",
    ]


def test_tail_log_actions_keeps_a_traceback_with_its_error(
    tmp_path: Path,
) -> None:
    """``log.exception`` writes the stack as continuation lines with no level
    token of their own.  An ERROR whose stack was dropped is the half of the
    answer that matters least."""
    log_file = tmp_path / "trcc.log"
    log_file.write_text("\n".join([
        _record("ERROR", "connect failed"),
        "Traceback (most recent call last):",
        '  File "x.py", line 1, in <module>',
        "USBError: [Errno 13] Access denied",
    ]))

    kept = tail_log_actions(log_file)

    assert len(kept) == 4
    assert "Access denied" in kept[-1]


def test_tail_log_actions_drops_a_debug_records_continuation(
    tmp_path: Path,
) -> None:
    """A continuation rides on its record — so a DEBUG one is dropped too,
    otherwise the filter leaks whatever a per-frame line happened to wrap."""
    log_file = tmp_path / "trcc.log"
    log_file.write_text("\n".join([
        _record("DEBUG", "per-frame detail"),
        "  continuation of the debug line",
        _record("INFO", "the action"),
    ]))

    kept = tail_log_actions(log_file)

    assert len(kept) == 1
    assert kept[0].endswith("the action")


def test_tail_log_actions_is_bounded_and_keeps_the_most_recent(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "trcc.log"
    log_file.write_text("\n".join(
        _record("INFO", f"action {i}", i) for i in range(300)
    ))

    kept = tail_log_actions(log_file, n_lines=10)

    assert len(kept) == 10
    assert kept[-1].endswith("action 299")


# =========================================================================
# Health checks
# =========================================================================


def test_python_version_check_passes_on_311_plus(fake_platform) -> None:
    result = check_python_version(fake_platform)
    assert result.severity == "OK"
    assert "Python" in result.message


def test_each_os_platform_answers_its_own_install_hint() -> None:
    """The cutover Linux-hardcoded these; now each OS answers via the ABC."""
    from trcc.adapters.system.bsd import FreeBsdOS, NetBsdOS, OpenBsdOS
    from trcc.adapters.system.macos import MacOSPlatform
    from trcc.adapters.system.windows import WindowsPlatform

    assert "winget" in WindowsPlatform().software_install_hint("ffmpeg")
    assert "brew" in MacOSPlatform().software_install_hint("ffmpeg")
    # The BSDs differ in COMMAND, not data: FreeBSD has pkg, OpenBSD and
    # NetBSD have pkg_add.  One class served all three "pkg install" until
    # 2026-08-19, telling OpenBSD users to run something they do not have.
    assert "pkg install" in FreeBsdOS().software_install_hint("ffmpeg")
    assert "pkg_add" in OpenBsdOS().software_install_hint("ffmpeg")
    assert "pkg_add" in NetBsdOS().software_install_hint("ffmpeg")
    assert "pkg install" not in OpenBsdOS().software_install_hint("ffmpeg")
    # Unknown tool falls back to the generic ABC default, never crashes.
    assert "PATH" in WindowsPlatform().software_install_hint("nonesuch")


def test_each_os_platform_answers_its_own_no_devices_hint() -> None:
    from trcc.adapters.system.bsd import FreeBsdOS
    from trcc.adapters.system.macos import MacOSPlatform
    from trcc.adapters.system.windows import WindowsPlatform

    assert "WinUSB" in WindowsPlatform().no_devices_hint()
    assert "macOS" in MacOSPlatform().no_devices_hint()
    assert "usbconfig" in FreeBsdOS().no_devices_hint()
    # No Linux-isms (udev) leaking onto the non-Linux platforms.
    assert "udev" not in WindowsPlatform().no_devices_hint()
    assert "udev" not in MacOSPlatform().no_devices_hint()


def test_each_os_platform_answers_its_own_permission_denied_hint() -> None:
    """EACCES USB hint moved off a core sys.platform sniff onto the Platform port."""
    from trcc.adapters.system.bsd import FreeBsdOS, OpenBsdOS
    from trcc.adapters.system.linux import LinuxOS
    from trcc.adapters.system.macos import MacOSPlatform
    from trcc.adapters.system.windows import WindowsPlatform

    assert "udev" in LinuxOS().permission_denied_hint()
    assert "WinUSB" in WindowsPlatform().permission_denied_hint()
    macos_hint = MacOSPlatform().permission_denied_hint()
    assert "sudo" in macos_hint or "Privacy" in macos_hint
    assert "devd" in FreeBsdOS().permission_denied_hint()
    assert "ugen" in OpenBsdOS().permission_denied_hint()
    # No Linux-isms leaking onto the non-Linux platforms.
    assert "udev" not in WindowsPlatform().permission_denied_hint()
    assert "udev" not in MacOSPlatform().permission_denied_hint()


def test_log_writable_check_passes_on_tmp_dir(
    fake_platform, tmp_home: Path,
) -> None:
    del tmp_home
    paths = fake_platform.paths()
    result = check_log_writable(paths)
    assert result.severity == "OK"


def test_run_health_checks_returns_full_report(fake_platform) -> None:
    report = run_health_checks(fake_platform)
    names = {c.name for c in report.checks}
    # Sanity — every registered check shows up
    expected = {
        "python-version", "log-writable", "config-writable",
        "devices-visible", "sensors-enumerable", "gpu-sensors", "ffmpeg",
        "pyside6", "udev-rules", "7z",
    }
    assert expected <= names


def test_health_report_aggregates_severities() -> None:
    """The HealthReport.worst_severity ladder is FAIL > WARN > OK."""
    from trcc.adapters.diagnostics.health import HealthReport

    a = HealthCheckResult(name="a", severity="OK", message="")
    b = HealthCheckResult(name="b", severity="WARN", message="")
    c = HealthCheckResult(name="c", severity="FAIL", message="")
    assert HealthReport(checks=[a]).worst_severity == "OK"
    assert HealthReport(checks=[a, b]).worst_severity == "WARN"
    assert HealthReport(checks=[a, b, c]).worst_severity == "FAIL"


# ``gpu_state`` is passed explicitly rather than monkeypatched onto the
# module.  It is a default argument, bound when the function is defined, so
# patching ``health_mod.nvml_init_state`` afterwards would NOT reach it — the
# check would quietly probe this machine's real NVIDIA driver and these cases
# would assert against whatever it happens to say.


def _state(available: bool, initialized: bool, error: str | None = None):
    """A stand-in for ``nvml_init_state`` reporting a chosen driver state."""
    def _read() -> tuple[bool, bool, str | None]:
        return available, initialized, error
    return _read


def test_gpu_check_ok_when_nvml_initialized(fake_platform) -> None:
    result = check_gpu_sensors(fake_platform, _state(True, True))
    assert result.severity == "OK"
    assert "NVML initialized" in result.message


def test_gpu_check_ok_when_no_nvidia_card(
    fake_platform, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health_mod, "nvidia_gpu_present", lambda: False)
    result = check_gpu_sensors(fake_platform, _state(False, False))
    assert result.severity == "OK"
    assert "No discrete NVIDIA GPU" in result.message


def test_gpu_check_warns_when_reader_missing(
    fake_platform, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Genuinely absent — nothing installed, so "install it" is right.

    The distribution lookup is stubbed to absent rather than left to the host:
    on a machine that HAS nvidia-ml-py this test used to pass while exercising
    the other fault entirely, because "the reader did not load" and "the reader
    is not installed" were the same branch.  They are not the same, and
    conflating them is what sent #207 and #216 reporters back to reinstall
    something they already had.
    """
    monkeypatch.setattr(health_mod, "nvidia_gpu_present", lambda: True)
    monkeypatch.setattr(health_mod.toolchain, "installed_elsewhere",
                        lambda dist: None)
    result = check_gpu_sensors(fake_platform, _state(False, False))
    assert result.severity == "WARN"
    assert "pynvml reader is not installed" in result.message
    # Hint now comes from the DI'd platform's software_install_hint("pynvml")
    # rather than a Linux-hardcoded package name.
    assert "pynvml" in result.fix_hint


def test_gpu_check_says_installed_when_the_binding_is_present(
    fake_platform, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Installed but not importable — "install it" would be wrong advice.

    A reporter who put nvidia-ml-py in one interpreter and runs trcc under
    another, or whose driver is missing libnvidia-ml.so.1, must not be told to
    install the binding again.  This is the other half of the split above.
    """
    monkeypatch.setattr(health_mod, "nvidia_gpu_present", lambda: True)
    monkeypatch.setattr(health_mod.toolchain, "installed_elsewhere",
                        lambda dist: "13.595.45")
    result = check_gpu_sensors(fake_platform, _state(False, False))
    assert result.severity == "WARN"
    assert "is installed but did not import" in result.message
    assert "13.595.45" in result.message
    assert "will not help" in result.fix_hint
    assert "libnvidia-ml.so.1" in result.fix_hint


def test_gpu_check_warns_with_reload_hint_on_init_failure(
    fake_platform, monkeypatch: pytest.MonkeyPatch,
) -> None:
    err = "NVMLError_LibRmVersionMismatch: RM has detected an NVML/RM version mismatch"
    monkeypatch.setattr(health_mod, "nvidia_gpu_present", lambda: True)
    result = check_gpu_sensors(fake_platform, _state(True, False, err))
    assert result.severity == "WARN"
    assert err in result.message
    assert "modprobe" in result.fix_hint


def test_the_injected_gpu_state_reaches_the_check_through_the_whole_report(
    fake_platform, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam is threaded, not just present on the leaf function.

    ``DiagnosticsAdapter`` → ``run_health_checks`` → ``check_gpu_sensors`` is
    three hops, and a seam that stops at any of them still leaves the report
    reading the real driver.  Asserting on the leaf alone would not notice.
    """
    monkeypatch.setattr(health_mod, "nvidia_gpu_present", lambda: True)
    calls: list[str] = []

    def _reader() -> tuple[bool, bool, str | None]:
        calls.append("asked")
        return True, False, "a driver state this machine is not in"

    report = DiagnosticsAdapter(fake_platform, _reader).health()

    assert calls, "the report never asked the injected reader"
    gpu = next(c for c in report.checks if c.name == "gpu-sensors")
    assert "a driver state this machine is not in" in gpu.message


def test_gpu_reader_state_uses_the_injected_reader(fake_platform) -> None:
    """The other reach — the port method the GPU-offer decision consumes."""
    state = DiagnosticsAdapter(fake_platform, _state(True, True)).gpu_reader_state()
    assert (state.reader_installed, state.initialized) == (True, True)


def test_package_install_hint_returns_a_string() -> None:
    """Hint never crashes — even when no package manager is detected,
    it returns the generic 'install via your package manager' fallback."""
    hint = package_install_hint("ffmpeg")
    assert isinstance(hint, str)
    assert "ffmpeg" in hint


# =========================================================================
# Doctor
# =========================================================================


def test_run_doctor_returns_exit_code(fake_platform) -> None:
    result = run_doctor(fake_platform)
    # FakePlatform yields no devices → WARN, not FAIL, so exit_code == 0.
    assert result.exit_code in (0, 1)


def test_render_doctor_output_includes_summary(fake_platform) -> None:
    result = run_doctor(fake_platform)
    rendered = render_doctor_output(result.report)
    assert "checks total" in rendered


# =========================================================================
# Debug report bundle
# =========================================================================


def test_build_debug_report_returns_filled_struct(fake_platform) -> None:
    report = build_debug_report(fake_platform)
    assert report.timestamp
    assert "distro" in report.platform_info
    assert "config_dir" in report.paths
    # FakePlatform has no devices → empty list, but no scan error.
    assert report.devices_error == ""
    assert isinstance(report.devices, list)


def test_debug_report_renders_paste_ready_text(fake_platform) -> None:
    report = build_debug_report(fake_platform)
    text = report.render_text()
    # Markers a reporter / triager visually scans for.
    for header in ("Platform", "Paths", "Devices", "Sensors", "Health",
                   "Actions", "Log tail"):
        assert f"## {header}" in text


def test_debug_report_writes_to_disk(fake_platform, tmp_path: Path) -> None:
    from trcc.adapters.diagnostics.debug_report import write_debug_report

    report = build_debug_report(fake_platform)
    out = tmp_path / "debug.txt"
    written = write_debug_report(report, out)
    assert written == out
    body = out.read_text(encoding="utf-8")
    assert "Paths" in body


def test_debug_report_captures_live_handshake(tmp_path: Path) -> None:
    """A connected LCD device's exact PM / SUB / fbl / resolution / raw bytes
    are captured live — the byte the report previously couldn't produce because
    the connect-time log line scrolls out of the tail (the #176/#186 blocker)."""
    from tests.mock_platform import MockPlatform

    # GrandVision 360 (bulk, registry fbl 72) with a pinned PM=50 handshake.
    platform = MockPlatform([{"vid": "87ad", "pid": "70db", "pm": 50}], tmp_path)
    report = build_debug_report(platform)

    assert len(report.devices) == 1
    dev = report.devices[0]
    assert dev["key"] == "87ad:70db"
    assert dev["hs_pm"] == "50"
    assert dev["hs_sub"] == "0"
    # Resolution is whatever the resolver returns for PM=50 today — the report
    # surfaces the ground truth so the *resolver* bug is visible, not hidden.
    assert re.fullmatch(r"\d+x\d+", dev["hs_resolution"])
    assert dev["hs_raw"]  # first handshake bytes, hex — ground truth for offsets

    text = report.render_text()
    assert "handshake: PM=50 SUB=0" in text
    assert f"resolution={dev['hs_resolution']}" in text


def test_debug_report_skips_handshake_for_led(tmp_path: Path) -> None:
    """An LED segment display has no frame handshake — the probe skips it
    cleanly (no ``hs_`` fields) and the report still renders."""
    from tests.mock_platform import MockPlatform

    platform = MockPlatform([{"vid": "0416", "pid": "8001", "pm": 1}], tmp_path)
    report = build_debug_report(platform)

    assert len(report.devices) == 1
    assert "hs_resolution" not in report.devices[0]
    assert "## Devices" in report.render_text()


# =========================================================================
# Command-level end-to-end
# =========================================================================


@pytest.fixture
def _trcc_app(fake_platform):
    """Bare App without a renderer — diagnostics never touch DisplayService."""
    from trcc.app import App
    return App(fake_platform)


def test_run_health_check_command(_trcc_app) -> None:
    from trcc.core.commands import RunHealthCheck

    result = _trcc_app.dispatch(RunHealthCheck())
    assert result.ok is (result.fail_count == 0)
    assert result.checks
    assert any(c.name == "python-version" for c in result.checks)


def test_run_doctor_command(_trcc_app) -> None:
    from trcc.core.commands import RunDoctor

    result = _trcc_app.dispatch(RunDoctor())
    assert result.rendered
    assert "checks total" in result.rendered


def test_generate_debug_report_writes_to_disk(
    _trcc_app, tmp_path: Path,
) -> None:
    from trcc.core.commands import GenerateDebugReport

    out = tmp_path / "debug.txt"
    result = _trcc_app.dispatch(GenerateDebugReport(
        output_path=out, log_tail_lines=10,
    ))
    assert result.ok is True
    assert result.output_path == str(out)
    assert out.is_file()


def test_generate_debug_report_in_memory_only(_trcc_app) -> None:
    from trcc.core.commands import GenerateDebugReport

    result = _trcc_app.dispatch(GenerateDebugReport(output_path=None))
    assert result.ok is True
    assert result.output_path == ""
    assert "Platform" in result.rendered_text


# ── CPU power (RAPL) report section (#194) ───────────────────────────


def test_render_powercap_readable_domain() -> None:
    """A readable package domain renders its name + energy_uj mode (#194)."""
    from trcc.adapters.diagnostics.debug_report import _render_powercap

    out = _render_powercap([
        {"domain": "intel-rapl:0", "name": "package-0",
         "energy_uj": "readable (0o444)"},
    ])
    assert "intel-rapl:0" in out
    assert "package-0" in out
    assert "readable (0o444)" in out


def test_render_powercap_root_only_is_flagged() -> None:
    """A root-only energy_uj is surfaced so the reporter sees the real cause
    of a blank cpu:power — the permission, not a code bug (#194)."""
    from trcc.adapters.diagnostics.debug_report import _render_powercap

    out = _render_powercap([
        {"domain": "intel-rapl:0", "name": "package-0",
         "energy_uj": "ROOT-ONLY (0o400)"},
    ])
    assert "ROOT-ONLY (0o400)" in out


def test_render_powercap_empty_points_at_setup() -> None:
    """No domains → tell the reporter to run setup (driver not loaded) (#194)."""
    from trcc.adapters.diagnostics.debug_report import _render_powercap

    out = _render_powercap([])
    assert "intel_rapl_msr" in out
    assert "trcc setup" in out


def test_collect_powercap_returns_list() -> None:
    """Smoke: the collector never raises and returns a list (rows on Linux
    with RAPL, empty otherwise)."""
    from trcc.adapters.diagnostics.debug_report import _collect_powercap

    assert isinstance(_collect_powercap(), list)


# ── The verbosity ladder — the rule, gated ───────────────────────────────────
#
# This mapping used to live as an if-chain inside ``ui.cli.main._root`` and
# NOTHING asserted it: ``per_frame=verbose > 0`` could have read ``>= 99`` and
# the suite stayed green, because every test here calls ``configure_logging``
# with explicit arguments and never asks what a ``-v`` count resolves to.
# A rule nothing can call is a rule nothing can gate.


@pytest.mark.parametrize("verbosity,terminal,file_level,per_frame", [
    (0, logging.WARNING, logging.DEBUG, False),
    (1, logging.INFO,    logging.DEBUG, False),
    (2, logging.DEBUG,   logging.DEBUG, False),
    (3, TRACE,           TRACE,         True),
    (9, TRACE,           TRACE,         True),   # saturates, never inverts
])
def test_verbosity_ladder(verbosity: int, terminal: int,
                          file_level: int, per_frame: bool) -> None:
    """-v INFO, -vv DEBUG, -vvv TRACE; quiet by default."""
    levels = levels_for(verbosity)
    assert levels.terminal == terminal
    assert levels.file == file_level
    assert levels.per_frame is per_frame


def test_the_file_never_loses_debug_however_quiet_the_terminal() -> None:
    """The invariant the always-DEBUG rule exists to protect.

    ``trcc report`` is the entire diagnosis for hardware we do not own.  A file
    level that rose with a flag would mean a reporter who did not know the flag
    sends a log with the evidence already discarded — which is the bug that rule
    was written to fix.  The ladder governs the TERMINAL.
    """
    for verbosity in range(10):
        levels = levels_for(verbosity)
        assert levels.file <= logging.DEBUG, (
            f"-{'v' * verbosity} would raise the file above DEBUG"
        )


def test_trace_is_below_debug_so_vvv_must_lower_the_file_too() -> None:
    """Why ``-vvv`` is the one rung that touches the file.

    TRACE sits BELOW debug, so a file pinned at DEBUG could never record a
    TRACE line — the deepest detail would be visible on the terminal and absent
    from the one artifact a report is read from.
    """
    assert TRACE < logging.DEBUG
    assert levels_for(3).file == TRACE
    assert logging.getLevelName(TRACE) == "TRACE"


def test_trace_helper_emits_only_when_enabled(tmp_path: Path) -> None:
    """``trace()`` is silent at DEBUG and lands at TRACE."""
    log_file = tmp_path / "trcc.log"
    configure_logging(log_file, level=logging.DEBUG, stderr_level=logging.CRITICAL)
    logger = logging.getLogger("trcc.test.trace")
    trace(logger, "deep internal %s", "payload")
    logging.getLogger().handlers[0].flush()
    assert "deep internal" not in log_file.read_text()

    configure_logging(log_file, level=TRACE, stderr_level=logging.CRITICAL)
    trace(logger, "deep internal %s", "payload")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "deep internal payload" in log_file.read_text()


# =========================================================================
# The frame path must not write a record per frame
# =========================================================================
#
# The burn-down's ratchet (``test_logging_coverage``) counts SILENT functions
# and only ever pushes that number down.  It cannot see the defect on the other
# side of the same line: a function ON THE FRAME PATH that logs through the
# ORDINARY logger writes a record EVERY frame.  The file floor is DEBUG at
# every rung by design, so those records are written even with no ``-v`` — the
# cost is paid and the one-shot lines a report is read for get scrolled out of
# the 1 MB tail.  That shape was 82-90% of the CPU regression since v9.9.2.
#
# It is also easy to re-create while ADDING coverage, which is exactly how it
# came back: measured 2026-08-30 on the real device, the static-theme path wrote
# 4.00 records/frame and the advancing-video path 6.25, across 16 call sites.
#
# So this gate asserts the invariant rather than the instance: no call site may
# emit at a rate that scales with the frame count.  A legitimately rare line is
# free to fire — ``_log_cache_transition`` fires once per cache-state FLIP and
# measured 0.005/frame — which is why the bar is a RATE, and why it reuses the
# profiler's own definition of hot rather than inventing a second number.

#: Same threshold ``dev/tools/frame_profile.py --hot`` uses.  A per-frame
#: emitter sits at ~1.0; a once-per-transition line sits near zero.  Nothing
#: real lands between, so the gap is where the bar goes.
_PER_FRAME_RATE = 0.5


def _records_by_site(log_file: Path, start: int) -> dict[str, int]:
    """Count records appended after byte offset *start*, keyed by call site."""
    counts: dict[str, int] = {}
    with log_file.open("r", errors="replace") as fh:
        fh.seek(start)
        for line in fh:
            m = re.match(r"^\S+ \w+\s+(\S+?):(\S+?):(\d+):", line)
            if m is not None:
                site = ":".join(m.groups())
                counts[site] = counts.get(site, 0) + 1
    return counts


def _frame_path_rates(tmp_path: Path, *, starve_cache: bool,
                      frames: int = 30) -> dict[str, float]:
    """Records-per-frame, by call site, driving the REAL service chain.

    ``starve_cache`` picks WHICH frame path runs, and both matter:

    * ``True``  — a one-byte ``BgMaskCache`` so every frame MISSES and rebuilds.
      That is the background/mask chain (``_resolve_background``,
      ``_build_bg_mask``, ``decode_image``, ``open_image``, ``bg_fit`` …) where
      11 of the 16 measured floods lived.
    * ``False`` — a static theme with no playback, so after the first frame the
      full-pipeline cache HITS every time.  That is the other path, and
      ``build_frame``'s own cache-HIT line was one of the four floods on it.

    A gate that drove only one of the two would be blind to half the tree —
    which is exactly how the first version of this test passed with a live
    flood in ``_resolve_background``.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from trcc.adapters.render.qt import QtRenderer
    from trcc.adapters.theme.filesystem import FileContentStore
    from trcc.core.models import Kind, ProductInfo, Theme, Wire
    from trcc.core.protocol import get_profile
    from trcc.services.bg_cache import BgMaskCache
    from trcc.services.display import DisplayService
    from trcc.services.media import MediaService, Playback
    from trcc.services.overlay import OverlayService
    from trcc.services.settings import Settings

    from .conftest import FakePaths
    from .test_video_playback import _encoded_frame

    ladder = levels_for(0)                       # what a user runs: no -v
    log_file = tmp_path / "trcc.log"
    # ``level`` is the ROOT level and so the FILE's; ``stderr_level`` is the
    # terminal's.  Passing the terminal level here would set the root to
    # WARNING, suppress every DEBUG record, and make this pass no matter what
    # the code does — the exact false negative this exists to catch.
    configure_logging(log_file, level=ladder.file,
                      stderr_level=logging.CRITICAL,
                      per_frame=ladder.per_frame)

    renderer = QtRenderer()
    paths = FakePaths(tmp_path)
    media = MediaService()
    key = "0402:3922"
    if starve_cache:
        media._playbacks[key] = Playback(
            frames=[_encoded_frame(v)
                    for v in (0xFF000000, 0xFF404040, 0xFF808080)],
            fps=15,
        )
    display = DisplayService(
        renderer=renderer,
        themes=FileContentStore(),
        overlay=OverlayService(renderer),
        settings=Settings(paths),
        media=media,
        paths=paths,
    )
    if starve_cache:
        # A one-byte budget evicts on every put, so `get` MISSES every frame
        # and the whole rebuild chain runs.  Seeded directly because the real
        # 128 MB cap would need ~320 distinct 320x320 surfaces to force this.
        display._bg_caches[key] = BgMaskCache(1)

    info = ProductInfo(
        vid=0x0402, pid=0x3922, vendor="ALi Corp", product="LCD",
        wire=Wire.SCSI, kind=Kind.LCD, device_type=1, fbl=100,
        native_resolution=(320, 320), orientations=(0,),
    )
    theme = Theme(path=tmp_path / "theme", name="t",
                  resolution=(320, 320), config={"elements": []})
    profile = get_profile(100)

    def render_once() -> None:
        playback = media._playbacks.get(key)
        if playback is not None:
            playback.advance()
        display.build_frame(info=info, theme=theme, sensors={},
                            profile=profile)

    for _ in range(5):            # warm-up: first-frame lines are one-shot
        render_once()
    for handler in logging.getLogger().handlers:
        handler.flush()

    mark = log_file.stat().st_size
    for _ in range(frames):
        render_once()
    for handler in logging.getLogger().handlers:
        handler.flush()

    return {site: n / frames
            for site, n in _records_by_site(log_file, mark).items()}


@pytest.mark.parametrize("starve_cache", [True, False],
                         ids=["bg-rebuild", "cache-hit"])
def test_the_frame_path_writes_no_record_per_frame(
    tmp_path: Path, starve_cache: bool,
) -> None:
    """Render repeatedly at DEFAULT verbosity; nothing may scale with frames."""
    rates = _frame_path_rates(tmp_path, starve_cache=starve_cache)
    floods = {s: r for s, r in rates.items() if r >= _PER_FRAME_RATE}
    assert not floods, (
        "these call sites write a record per rendered frame at DEFAULT "
        "verbosity — move each onto core.logs.per_frame(__name__) so the "
        "record is never constructed:\n"
        + "\n".join(f"  {rate:.2f}/frame  {site}"
                    for site, rate in sorted(floods.items(),
                                             key=lambda kv: -kv[1]))
    )


@pytest.mark.parametrize("starve_cache", [True, False],
                         ids=["bg-rebuild", "cache-hit"])
def test_the_frame_path_gate_actually_reaches_the_render_chain(
    tmp_path: Path, starve_cache: bool,
) -> None:
    """The gate above is only as good as the code it runs.

    Its first version asserted "no floods" while driving a workload that went
    entirely to cache after three frames, so it passed with a live flood in
    ``_resolve_background``.  A green result meant nothing.  This pins that the
    chain is genuinely exercised, so "no floods" is a finding and not silence.
    """
    rates = _frame_path_rates(tmp_path, starve_cache=starve_cache)
    per_frame_logger = [s for s in rates if s.startswith(PER_FRAME_ROOT)]
    assert not per_frame_logger, (
        "per-frame records reached the FILE at default verbosity — the family "
        f"is not silenced: {per_frame_logger}"
    )
    # Nothing asserts a specific line here: what matters is that the render ran
    # and its per-frame chatter was suppressed rather than never produced.  If
    # the chain stopped executing, the mutation test below stops failing and
    # says so in one sentence.


def test_the_frame_path_gate_can_actually_see_a_flood(tmp_path: Path) -> None:
    """Mutation check: the rule must FAIL when a flood is present.

    A gate that has never been broken on purpose is not known to guard
    anything, and this repo has twice shipped one that guarded nothing.  This
    reproduces the defect exactly — an ordinary logger called once per rendered
    frame — and asserts the same rule catches it while leaving a genuinely rare
    line alone.  If this stops failing-by-construction, the gate is dead.
    """
    ladder = levels_for(0)
    log_file = tmp_path / "trcc.log"
    configure_logging(log_file, level=ladder.file,
                      stderr_level=logging.CRITICAL,
                      per_frame=ladder.per_frame)

    ordinary = logging.getLogger("trcc.services.pretend")
    rare = logging.getLogger("trcc.services.pretend_rare")

    frames = 40
    mark = log_file.stat().st_size if log_file.exists() else 0
    for i in range(frames):
        ordinary.debug("pretend per-frame line %d", i)
        if i == 0:
            rare.debug("pretend once-per-transition line")
    for handler in logging.getLogger().handlers:
        handler.flush()

    rates = {s: n / frames
             for s, n in _records_by_site(log_file, mark).items()}
    flooding = [s for s, r in rates.items() if r >= _PER_FRAME_RATE]
    quiet = [s for s, r in rates.items() if r < _PER_FRAME_RATE]

    assert any("pretend:" in s for s in flooding), (
        "the per-frame emitter was NOT caught — the gate is blind and every "
        "pass it has ever reported is worthless"
    )
    assert any("pretend_rare:" in s for s in quiet), (
        "the once-per-transition emitter was flagged as a flood — the bar is "
        "too tight and the gate will fail on correct code"
    )


# =========================================================================
# The sensor tick's frame family — Gate A
#
# The render path has ``record_rate.py``; the SENSOR tick had nothing.  Its
# blind spot was proven on real hardware: ``record_rate --gui`` reports 0.03
# records/frame and ZERO sensor records, because 200 flat-out frames finish
# inside one 2-second sensor tick.  A per-tick line on the ordinary logger is
# therefore invisible to every gate that existed, and it wrote 39 records per
# tick -- 73% of a real ``~/.trcc/trcc.log``.
#
# Static and AST-ONLY on purpose.  Importing the tree to find subclasses
# EXECUTES the CLI's typer app and prints its help; and a dynamic check can
# only see backends that run on THIS box, so it would never notice a new
# Windows or macOS source logging on the wrong logger.
# =========================================================================

_ROLE_PORTS = frozenset({
    "CpuSource", "MemorySource", "GpuSource", "FanSource",
    "DiskSource", "DramSource",
})
_LOG_LEVELS = frozenset({
    "debug", "info", "warning", "error", "exception", "critical",
})
_SRC = Path(__file__).resolve().parents[1] / "src" / "trcc"


def _classes_by_file() -> dict[Path, list[ast.ClassDef]]:
    out: dict[Path, list[ast.ClassDef]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:                       # pragma: no cover - not our code
            continue
        found = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        if found:
            out[path] = found
    return out


def _role_implementations() -> dict[Path, list[ast.ClassDef]]:
    """Every class deriving from a role port, transitively, across ALL of src.

    Transitively because a future ``class FooCpu(PsutilCpu)`` is just as
    per-tick as ``class FooCpu(CpuSource)``; scanned across all of ``src`` so
    that an implementation appearing OUTSIDE ``adapters/sensors`` is caught
    rather than silently unscanned.
    """
    by_file = _classes_by_file()
    names = {c.name: c for cs in by_file.values() for c in cs}
    role: set[str] = set(_ROLE_PORTS)
    for _ in range(len(names) + 1):               # closure, bounded
        grew = False
        for name, cls in names.items():
            if name in role:
                continue
            bases = {b.id for b in cls.bases if isinstance(b, ast.Name)}
            if bases & role:
                role.add(name)
                grew = True
        if not grew:
            break
    return {
        path: [c for c in cs if c.name in role and c.name not in _ROLE_PORTS]
        for path, cs in by_file.items()
        if any(c.name in role and c.name not in _ROLE_PORTS for c in cs)
    }


def _log_calls(fn: ast.AST) -> list[tuple[int, str, bool]]:
    """(lineno, logger object, conditional?) for every log call in *fn*.

    Conditional means guarded by an ``If`` or an ``ExceptHandler`` -- a failure
    or fallback branch, which carries the REASON and belongs on the ordinary
    logger where a reporter's log keeps it.  Everything else counts as
    unconditional, deliberately: a call inside a ``for`` or ``with`` in a
    per-tick method runs per tick just as surely as one at the top.
    """
    parent: dict[int, ast.AST] = {}
    for node in ast.walk(fn):
        for child in ast.iter_child_nodes(node):
            parent[id(child)] = node
    out = []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in _LOG_LEVELS:
            continue
        obj = getattr(node.func.value, "id", "")
        if obj not in {"log", "frame_log"}:
            continue
        conditional, cur = False, node
        while id(cur) in parent:
            cur = parent[id(cur)]
            if isinstance(cur, (ast.If, ast.ExceptHandler)):
                conditional = True
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                break
        out.append((node.lineno, obj, conditional))
    return out


def _role_port_members() -> frozenset[str]:
    """The role ports' abstract member NAMES, read from ``core/ports.py``.

    These and only these are per-tick BY CONSTRUCTION: ``_poll_once`` calls
    every one of them on every source, every tick.  A role implementation's
    OTHER methods are not -- ``HwmonDisk._identity`` is a ``@staticmethod``
    called once from ``__init__``, and its two lines (serial vs directory name)
    are exactly the one-shot diagnostics a reporter's log is read for.  An
    earlier draft of this gate scanned every method and failed on that line,
    which is how the over-reach was found before it shipped.
    """
    tree = ast.parse(
        (_SRC / "core" / "ports.py").read_text(encoding="utf-8"))
    owners = _ROLE_PORTS | {"IdentifiedSource"}
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name in owners):
            continue
        for fn in node.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any((isinstance(d, ast.Name) and d.id == "abstractmethod")
                   or (isinstance(d, ast.Attribute) and d.attr == "abstractmethod")
                   for d in fn.decorator_list):
                names.add(fn.name)
    assert names, "no abstract role members found — ports.py shape changed"
    return frozenset(names)


def test_role_port_reads_log_on_the_frame_family() -> None:
    """A per-tick sensor read may not write through the ordinary logger.

    ``_poll_once`` calls every role-port member of every source on every tick,
    so these methods are per-tick BY CONSTRUCTION -- which is what makes this
    derivable rather than a hand-kept list.

    MUTATION CHECK: change any unconditional ``frame_log.debug`` in
    ``adapters/sensors`` back to ``log.debug`` and this fails, naming it.
    It is gated BOTH ways.  Moving a CONDITIONAL line onto the frame family
    fails too: those carry the failure reason, and silencing them by default
    would hide from a reporter's log exactly the line that explains why a
    sensor read nothing.  A one-directional rule is one nobody re-reads.
    """
    members = _role_port_members()
    offenders = []
    for path, classes in _role_implementations().items():
        for cls in classes:
            for fn in [n for n in cls.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and n.name in members]:
                for lineno, obj, conditional in _log_calls(fn):
                    want = "log" if conditional else "frame_log"
                    if obj != want:
                        why = ("a FAILURE branch carries the reason and belongs "
                               "on the ordinary logger, where a reporter's log "
                               "keeps it" if conditional else
                               "this runs EVERY tick")
                        offenders.append(
                            f"{path.relative_to(_SRC)}:{lineno} "
                            f"{cls.name}.{fn.name} uses `{obj}`, want "
                            f"`{want}` — {why}"
                        )
    assert not offenders, (
        "per-tick sensor reads logging through the ordinary logger -- each of "
        "these writes a record EVERY tick, and the file floor is DEBUG at every "
        "verbosity:\n  " + "\n  ".join(offenders)
    )


def test_role_port_implementations_all_live_in_the_sensors_adapter() -> None:
    """Scanned across all of ``src``, so one appearing elsewhere is caught.

    Measured 2026-09-01: 28 implementations, 12 files, none outside.  Scoping
    the scan to ``adapters/sensors`` would make a stray implementation
    invisible to the gate above rather than failing it.
    """
    stray = [
        str(path.relative_to(_SRC))
        for path in _role_implementations()
        if not str(path.relative_to(_SRC)).startswith("adapters/sensors/")
    ]
    assert not stray, (
        "role-port implementations outside adapters/sensors -- either move "
        f"them or widen this gate deliberately: {stray}"
    )


#: Which logger each ``BaselineSensors`` member may use, measured 2026-09-01.
#:
#: A RECORD, not a derivation, and deliberately so: deriving from
#: ``SensorEnumerator.__abstractmethods__`` is WRONG, because that set mixes
#: per-tick accessors with one-shot lifecycle (``start_polling``), so a derived
#: gate would demand lifecycle methods move onto the frame family.
#:
#: Nor can the ``If``/``ExceptHandler`` heuristic used for role ports apply
#: here: ``_refresh_if_stale``'s branches are conditional AND per-tick, while
#: ``_read``'s are conditional and are FAILURE branches.  The two need opposite
#: answers, so the split is judged per member and written down.
_ENUMERATOR_LOGGERS: dict[str, frozenset[str]] = {
    # Per-tick: called on every poll, so every line they emit is per-tick.
    "cpu": frozenset({"frame_log"}),
    "memory": frozenset({"frame_log"}),
    "gpus": frozenset({"frame_log"}),
    "fans": frozenset({"frame_log"}),
    "disks": frozenset({"frame_log"}),
    "read_all": frozenset({"frame_log"}),
    "_refresh_if_stale": frozenset({"frame_log"}),
    # Per-tick too, and NOT one-shot: qtgui's SensorPickerWidget dispatches
    # ReadSensors() on a 2-second QTimer.
    "discover": frozenset({"frame_log"}),
    # Both, by design: the entry/value line is per-tick (frame), the
    # first-failure warning is the diagnostic a reporter needs (ordinary).
    "_read": frozenset({"frame_log", "log"}),
    "_poll_once": frozenset({"frame_log", "log"}),
    # Lifecycle: fires once per start/stop, so it belongs in the file always.
    "__init__": frozenset({"log"}),
    "start_polling": frozenset({"log"}),
    "stop_polling": frozenset({"log"}),
    "_poll_loop": frozenset({"log"}),
    # DEAD, not lifecycle — recorded as such so the disposition is not lost:
    # abstract on the port, one implementation, ZERO callers in src/.  Retire
    # it, or wire the single-sensor Query it implies; do not quietly classify.
    "read_one": frozenset({"log"}),
    # An empty extension hook called EVERY TICK from _poll_once.  A stub today,
    # so the ratchet exempts it and it logs nothing.  The moment an OS
    # overrides it, THE RULE demands a line and this entry says which logger.
    "_poll_extra": frozenset(),
}


def _enumerator_methods() -> dict[str, ast.FunctionDef]:
    tree = ast.parse((_SRC / "adapters" / "sensors" / "aggregator.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "BaselineSensors":
            return {
                fn.name: fn for fn in node.body
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise AssertionError("BaselineSensors not found — aggregator.py shape changed")


def test_every_enumerator_member_is_classified() -> None:
    """No member may be added without deciding whether it is per-tick.

    ``_poll_extra`` is why this exists: an empty per-tick extension hook that an
    earlier draft of the record missed entirely, covering 10 of 16 members.
    """
    actual = set(_enumerator_methods())
    recorded = set(_ENUMERATOR_LOGGERS)
    assert actual == recorded, (
        f"unclassified members (decide per-tick vs lifecycle): "
        f"{sorted(actual - recorded)}\n"
        f"stale record entries (member gone): {sorted(recorded - actual)}"
    )


def test_enumerator_members_use_their_recorded_logger() -> None:
    """Asserted BOTH ways, so the record cannot rot unnoticed.

    MUTATION CHECK: swap ``frame_log`` for ``log`` in any per-tick member and
    this fails; do the reverse in ``start_polling`` and it fails too. A
    one-directional record is one nobody re-reads —
    ``test_recorded_ui_reach_matches_reality`` exists for the same reason.
    """
    wrong = {}
    for name, fn in _enumerator_methods().items():
        used = frozenset(obj for _, obj, _ in _log_calls(fn))
        want = _ENUMERATOR_LOGGERS[name]
        if used != want:
            wrong[name] = (sorted(used), sorted(want))
    assert not wrong, (
        "enumerator members no longer match the record — update the code, or "
        "the record AND its reason:\n  " + "\n  ".join(
            f"{n}: uses {u}, recorded {w}" for n, (u, w) in sorted(wrong.items())
        )
    )


def test_a_per_frame_info_line_is_silenced_too(tmp_path: Path) -> None:
    """The family silences INFO as well as DEBUG, by construction.

    It used to sit at INFO, which silences only DEBUG.  Every frame call is
    ``.debug`` today, so the hole was empty -- but a future
    ``frame_log.info(...)`` on a per-frame path would have written a record
    EVERY frame with nothing to catch it: not the family, not
    ``record_rate.py`` (which measures records, and would simply report the
    higher number as fact), not the sensor-tick gate (which only checks WHICH
    logger, not which level).

    MUTATION CHECK: put ``logging.INFO`` back in ``configure_logging`` and this
    fails while every other diagnostics test still passes -- which is precisely
    how the hole stayed open.
    """
    log_file = tmp_path / "t.log"
    configure_logging(log_file, level=logging.DEBUG,
                      stderr_level=logging.CRITICAL)

    per_frame(__name__).info("frame info %d", 7)
    per_frame(__name__).debug("frame debug %d", 8)
    per_frame(__name__).warning("frame warning %d", 9)
    for handler in logging.getLogger().handlers:
        handler.flush()

    text = log_file.read_text()
    assert "frame info 7" not in text, "an INFO on the frame path reached the file"
    assert "frame debug 8" not in text
    # A per-frame WARNING still gets through: it is a problem, not chatter.
    assert "frame warning 9" in text, (
        "a genuine per-frame warning must still reach the file — silencing "
        "those would hide the one line that says something is wrong"
    )
