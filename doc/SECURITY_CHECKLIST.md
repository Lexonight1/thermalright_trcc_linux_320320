# Security Checklist — TRCC Linux 🔒

This document summarizes the prioritized security measures, quick checks, and next steps needed to move TRCC Linux toward production readiness.

---

## 1) Must‑have actions (high priority) ✅
- [ ] **Harden binary parsers** (e.g., `src/trcc/dc_parser.py`) — validate field sizes, bounds, and fail-fast on malformed input. Add unit tests for edge cases. 🧪
- [ ] **Add fuzz tests** for `dc_parser` and other binary readers (Hypothesis/Atheris). Start with Hypothesis property tests and escalate to native fuzzing if needed. ⚠️
- [ ] **Safe archive extraction** — replace `tar.extractall()` / `zip.extractall()` with a vetted `safe_extract()` (reject absolute paths, `..`, symlinks). Review `src/trcc/theme_downloader.py`. 📦
- [ ] **Require download verification** — enforce HTTPS and require `sha256` checksums or signatures before installing remote theme packs. Verify checksums at download time. 🔗
- [ ] **Least privilege for device access** — tighten `99-trcc.rules` and ensure `trcc-quirk-fix.service` runs as an unprivileged user with `NoNewPrivileges=yes`, `ProtectSystem=full`, `ProtectHome=yes`, `PrivateTmp=yes`. 🔐
- [ ] **Subprocess hardening** — ensure all `subprocess` calls use list args, validate/whitelist any user-influenced inputs, and catch `TimeoutExpired`/`CalledProcessError`. Apply resource/time limits for media processing. ⏱️
- [ ] **Eliminate bare `except:`** and use specific exceptions (e.g., `struct.error`, `IndexError`, `OSError`, `subprocess.TimeoutExpired`). Use structured `logging` instead of `print()`. 🧾

## 2) Recommended actions (medium priority) 🔧
- [ ] **Enable signed releases & checksums** — GPG-sign artifacts and publish checksums with releases. ✅
- [ ] **CI enforcement & triage** — keep `pip-audit`, `safety`, `bandit`, CodeQL active (we added these). Decide which findings block merges and document triage workflow (we auto-create issues on high/critical findings). 🧰
- [ ] **Add pre-commit hooks** — `ruff`, `pytest`, `bandit`, `detect-secrets`, and `pip-audit` for local developer checks. 🪛
- [ ] **Sandbox heavy processing** — run media processing (ffmpeg/OpenCV) in constrained subprocesses or containers; enforce time/memory limits. 🐳
- [ ] **Secrets & repo hygiene** — scan repo for secrets and add secret detection to pre-commit; rotate any exposed keys. 🔑

## 3) Nice-to-have (longer term) ✨
- [ ] **Fuzzing harness with Atheris** for native code paths. 
- [ ] **SLSA provenance / reproducible builds** for stronger supply-chain guarantees. 📜
- [ ] **Runtime monitoring & opt‑in crash reporting** (privacy-first). 📈
- [ ] **Periodic malware scans in CI** (scheduled ClamAV job that uploads reports). 🧹

---

## Quick local checks / commands 🧾
- Update ClamAV and scan repo:

```
sudo apt update && sudo apt install clamav clamav-freshclam -y
sudo freshclam
clamscan -r --infected --no-summary .
```

- Dependency & code security scans:

```
python -m pip install pip-audit safety bandit
python -m pip_audit
safety check --full-report
bandit -r src -f json -o bandit_report.json
```

- Run tests and linters (CI mirrors these):

```
python -m pip install -e '.[dev]'
ruff check .
pytest -q
```

---

## Files & CI we already added
- CI workflows: `.github/workflows/ci.yml` (tests, lint, build, security-scans) and `.github/workflows/release.yml` (build & release). ✅
- CodeQL: `.github/workflows/codeql-analysis.yml` (scheduled + PR analysis). 🧠
- Dependabot: `.github/dependabot.yml` (daily pip, weekly GH Actions updates). 🔁
- Security issue template: `.github/ISSUE_TEMPLATE/security-report.md` and `SECURITY.md` (disclosure policy). 📬
- Auto-triage: CI job `security-triage` creates issues when high/critical findings are present. 🤖

---

## Acceptance criteria & next steps ✅
- **Acceptance**: Parsers have unit tests + fuzz tests; downloads verify checksums; safe extraction is in place; CI flags high/critical findings as issues; systemd & udev rules documented and validated on target distros.
- **Next step recommendation**: Implement `safe_extract()` in `src/trcc/theme_downloader.py`, replace `extractall()` usage, and add unit tests for archive safety. (I can implement this for you.)

---

If you'd like, I can: 
- implement `safe_extract()` and tests now, or
- scaffold Hypothesis fuzz tests for `dc_parser`, or
- add scheduled ClamAV CI job to upload scan reports.

Pick one and I'll proceed. 🔧
