# Code Audit, Security Review & CI/CD — borgui.borg_ui Collection

**Date**: 2026-03-25
**Status**: Approved
**Scope**: `ansible-collection-borg-ui` standalone repo

## Goal

Harden the collection code, raise test coverage from 71% to 90%+, and add CI
workflows for security scanning and coverage enforcement.

## 1. Security Fixes

### 1.1 Consolidate duplicate JWT minting

`_mint_jwt()` is duplicated in `borg_ui_client.py:36-62` and `borg_ui_jwt.py:93-109`.
Move the canonical implementation to `borg_ui_common.py` and import from both locations.
This ensures a security fix applies everywhere.

### 1.2 Timeout validation

`BorgUIClient.__init__()` accepts any timeout value including `None` or `0`, which
disables the timeout and lets modules hang forever. Add validation: `timeout` must be
a positive number, default 30 seconds.

### 1.3 SSL context only for HTTPS

`BorgUIClient.__init__()` creates an insecure SSL context even for HTTP URLs. Only
disable certificate verification when `insecure=True` AND `base_url` starts with
`https://`.

### 1.4 API response field validation

Multiple modules use response fields without validating they exist:
- `borg_ui_backup.py:342` — `job_id = resp.get("job_id")` then uses it in URL as
  `/api/backup/status/None` if missing
- `borg_ui_backup.py:303` — `last_resp = client.get(...)` could be `None` (empty body),
  then `last_resp.get("status")` raises `AttributeError`
- `borg_ui_repository.py:594` — `resp.get("repository", desired)` silently falls back
  to the desired dict if API response is empty/malformed
- `borg_ui_notification.py:392` — same silent fallback pattern

Fix: validate required fields in API responses before using them. Handle `None`
returns from `_request()` when the API body is empty. Raise `BorgUIClientError`
with a clear message if a required field is missing.

### 1.5 Cap error message length

`BorgUIClientError` can include arbitrarily large API response bodies via `body_str`
at `borg_ui_client.py:143`. Cap the included body to 500 characters.

### 1.6 Secret key file error handling

`borg_ui_client.py:102-104` reads `secret_key_file` with no error handling:
```python
with open(secret_key_file, "r") as fh:
    key = fh.read().strip()
```
A missing file, empty file, or permission error raises a raw `FileNotFoundError` or
`IOError` that produces an unformatted traceback instead of a clean `fail_json`.
Fix: wrap in `try/except OSError`, raise `BorgUIClientError` with a clear message.
Also validate the file is not empty after reading.

## 2. New Feature: `use_sudo` support for SSH connections

Upstream Borg UI v1.77.0 added `use_sudo` (boolean) to the SSH connection model,
allowing backups to run with sudo on remote hosts. The API returns `use_sudo` in
GET responses and accepts it in PUT updates on `/api/ssh-keys/connections/{id}`.

### Changes to `borg_ui_connection.py`

Follow the existing `use_sftp_mode` pattern exactly:
- Add `use_sudo` to `DOCUMENTATION` options block (type: bool, default: false)
- Add `use_sudo` to the argument spec dict
- Add `"use_sudo"` to `_MUTABLE_FIELDS` list
- Add `"use_sudo": params["use_sudo"]` to `_build_payload()`
- Add example showing `use_sudo: true` usage

### Tests

Add to `test_borg_ui_connection.py`:
- Test that `use_sudo` appears in the built payload
- Test that `_needs_update()` detects a `use_sudo` change
- Test that `use_sudo: false` (default) produces no update when existing is also false

## 3. Code Quality Fixes (renumbered from 2)

### 2.1 Clean up notification response parsing

`_find_notification_by_name()` in `borg_ui_notification.py:326-332` has an unreachable
defensive branch. The `isinstance(items, dict)` check on line 331 handles a case no
supported API response produces. Simplify to handle the two documented response
formats (list or dict with `notifications` key) and remove the unreachable branch.

### 2.2 Verify no_log annotations

Verify all modules mark `secret_key`, `secret_key_file`, `token`, and `passphrase`
parameters with `no_log: True`. Specifically check `secret_key_file` in
`AUTH_ARG_SPEC` (`borg_ui_common.py:23`) — file paths are not secrets but the field
should be consistent with how other Ansible collections handle credential file paths.

## 4. Test Coverage (target: 90%+)

### Current state

| File | Coverage | Gap |
|------|----------|-----|
| `borg_ui_client.py` | 92% | HTTP error codes beyond 404 |
| `borg_ui_common.py` | 30% | `validate_auth()`, `make_client()` |
| `borg_ui_backup.py` | 28% | Module execution paths, poll loop |
| `borg_ui_connection.py` | 41% | Module execution paths |
| `borg_ui_notification.py` | 48% | Module execution paths |
| `borg_ui_repository.py` | 45% | Module execution, cascade delete |
| `borg_ui_schedule.py` | 51% | Module execution paths |

### Approach

Mock `AnsibleModule` and `BorgUIClient` to test module execution without a live
Borg UI instance. Each module gets tests for:
- Present (create) path
- Present (update / no-change) path
- Absent (delete) path
- Check mode (no mutations)
- Error handling (API failures)

Additional targeted tests:
- `borg_ui_common.py`: `validate_auth()`, `make_client()` with all auth methods
- `borg_ui_client.py`: HTTP error codes 400/401/403/500, empty response body, invalid JSON
- `borg_ui_client.py`: secret key file error cases (missing, empty, permission denied)
- `borg_ui_client.py`: JWT expiry claim validation
- `borg_ui_repository.py`: cascade delete flow with multiple referencing schedules
- `borg_ui_backup.py`: `_poll_until_complete` branching — completed, failed, cancelled,
  and timeout paths (highest-risk untested area)

### Target

Overall coverage: 90%+. Each module file: 85%+.

## 5. CI/CD Workflows

### 4.1 Security workflow (`security.yml`)

**Triggers**: push to main, pull requests, weekly schedule (Monday 09:00 UTC)

Jobs:
- **pip-audit**: scan Python dependencies for known vulnerabilities. Requires
  `requirements-dev.txt` with pinned test dependencies (`pytest`, `pytest-mock`,
  `coverage`) to give pip-audit something to scan.
- **Trivy filesystem scan**: detect secrets, license issues, vulnerable patterns;
  upload SARIF results
- **CodeQL**: GitHub's static analysis for Python security patterns

### 4.2 Coverage workflow (`coverage.yml`)

**Triggers**: push to main, pull requests

Jobs:
- Run `coverage run --source=plugins -m pytest tests/unit/`
- `coverage report --fail-under=90`
- Upload coverage report as artifact

Note: `--source=plugins` restricts measurement to plugin source code only, excluding
test files and shim code that would inflate the number.

### 4.3 Existing workflow updates (`ansible-collection.yml`)

No structural changes needed. Note: the sanity check step uses `|| true` which
silently ignores failures — this is intentional during collection development but
should be revisited once the collection is stable.

### 4.4 New file: `requirements-dev.txt`

Required by pip-audit and for reproducible CI:
```
pytest>=7.0,<9
pytest-mock>=3.0,<4
coverage>=7.0,<8
```

## Implementation Order

1. Security fixes (consolidate JWT, timeout, SSL, response validation, error cap, file handling)
2. Code quality fixes (notification cleanup, no_log audit)
3. Test coverage expansion (common → client → modules, with poll loop priority)
4. CI workflows (security.yml, coverage.yml, requirements-dev.txt)
5. Final verification (all tests pass, coverage >= 90%, CI green)
