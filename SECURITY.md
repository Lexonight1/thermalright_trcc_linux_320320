# Security & Vulnerability Disclosure Policy

We appreciate responsible disclosure. If you discover a security vulnerability in this project, please follow these steps to report it safely:

1. If the vulnerability is high/critical or may expose sensitive data, open a private issue.
2. Include the scanner output (bandit_report.json, pip_audit_results.json, safety_report.json) and a minimal reproduction if possible.
3. Do not post public proof-of-concept code that exposes user data or credentials.
4. The maintainers aim to acknowledge receipt within 48 hours and provide a remediation timeline.

In non-sensitive cases, you may open a public issue using the security report template (`.github/ISSUE_TEMPLATE/security-report.md`), and add the label `security`.

Thank you for helping keep TRCC Linux secure.

## Known Limitations

- **Cloud theme downloads use HTTP**: Thermalright's cloud servers (`czhorde.cc`, `czhorde.com`) do not support HTTPS (port 443 refused). Downloads are unencrypted and vulnerable to MITM. This matches the Windows TRCC client behavior and cannot be fixed on our end. No integrity checksums are available from the upstream server.
- **API token auth is optional**: The REST API binds to localhost by default. Token auth (`--token`) is available but not enforced. Do not expose the API to untrusted networks without a token.
