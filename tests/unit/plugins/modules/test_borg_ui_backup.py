# -*- coding: utf-8 -*-
"""Unit tests for borg_ui_backup module."""

import sys
import os
import types
import pytest

TESTS_DIR = os.path.dirname(__file__)
ANSIBLE_DIR = os.path.abspath(os.path.join(TESTS_DIR, "..", "..", "..", ".."))
MU_PATH = os.path.join(ANSIBLE_DIR, "plugins", "module_utils")
MOD_PATH = os.path.join(ANSIBLE_DIR, "plugins", "modules")


def _ensure_pkg(name, path_hint=None):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        mod.__path__ = [path_hint] if path_hint else []
        mod.__package__ = name
        sys.modules[name] = mod
    return sys.modules[name]


_ensure_pkg("ansible_collections")
_ensure_pkg("ansible_collections.borgui")
_ensure_pkg("ansible_collections.borgui.borg_ui")
_ensure_pkg("ansible_collections.borgui.borg_ui.plugins")
_ensure_pkg("ansible_collections.borgui.borg_ui.plugins.module_utils", MU_PATH)
_ensure_pkg("ansible_collections.borgui.borg_ui.plugins.modules", MOD_PATH)

if "ansible" not in sys.modules:
    sys.modules["ansible"] = types.ModuleType("ansible")
if "ansible.module_utils" not in sys.modules:
    sys.modules["ansible.module_utils"] = types.ModuleType("ansible.module_utils")
if "ansible.module_utils.basic" not in sys.modules:
    basic = types.ModuleType("ansible.module_utils.basic")
    class _FM:
        def __init__(self, **kw): pass
    basic.AnsibleModule = _FM
    sys.modules["ansible.module_utils.basic"] = basic


def _load_source(module_name, file_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_load_source("ansible_collections.borgui.borg_ui.plugins.module_utils.borg_ui_client",
             os.path.join(MU_PATH, "borg_ui_client.py"))
_load_source("ansible_collections.borgui.borg_ui.plugins.module_utils.borg_ui_common",
             os.path.join(MU_PATH, "borg_ui_common.py"))
backup_mod = _load_source(
    "ansible_collections.borgui.borg_ui.plugins.modules.borg_ui_backup",
    os.path.join(MOD_PATH, "borg_ui_backup.py"),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REPOS = [
    {"id": 1, "name": "vault-01", "path": "/backups/vault-01"},
    {"id": 2, "name": "gitlab-01", "path": "/backups/gitlab-01"},
]

JOB_RUNNING = {
    "id": 42,
    "repository": "/backups/vault-01",
    "status": "running",
    "progress": 45,
    "started_at": "2024-01-01T02:00:00",
    "completed_at": None,
    "error_message": None,
    "logs": None,
    "progress_details": {
        "progress_percent": 45,
        "nfiles": 100,
        "current_file": "/opt/test.txt",
    },
}

JOB_COMPLETED = dict(JOB_RUNNING, status="completed", progress=100, logs="Backup done.")
JOB_FAILED = dict(JOB_RUNNING, status="failed", error_message="Borg lock error")


class MockClient:
    def __init__(self):
        self.calls = []
        self._responses = {}
        self._post_resp = None

    def get(self, path):
        self.calls.append(("GET", path))
        return self._responses.get(path)

    def post(self, path, data=None):
        self.calls.append(("POST", path, data))
        return self._post_resp


# ---------------------------------------------------------------------------
# Tests for _resolve_repository_path
# ---------------------------------------------------------------------------

from ansible_collections.borgui.borg_ui.plugins.module_utils.borg_ui_client import (
    BorgUIClientError,
)


class TestResolveRepositoryPath:
    def test_resolves_by_name(self):
        client = MockClient()
        client._responses["/api/repositories/"] = {"repositories": REPOS}
        path = backup_mod._resolve_repo_path(client, "vault-01")
        assert path == "/backups/vault-01"

    def test_raises_on_unknown_name(self):
        client = MockClient()
        client._responses["/api/repositories/"] = {"repositories": REPOS}
        with pytest.raises(BorgUIClientError, match="not found"):
            backup_mod._resolve_repo_path(client, "nonexistent")

    def test_raises_on_empty_repos(self):
        client = MockClient()
        client._responses["/api/repositories/"] = {"repositories": []}
        with pytest.raises(BorgUIClientError):
            backup_mod._resolve_repo_path(client, "vault-01")


# ---------------------------------------------------------------------------
# MockModule for execution-path tests
# ---------------------------------------------------------------------------

class _ExitJson(Exception):
    pass


class _FailJson(Exception):
    pass


class MockModule:
    def __init__(self, params, check_mode=False):
        self.params = params
        self.check_mode = check_mode
        self._result = None
        self._failed = False

    def exit_json(self, **kwargs):
        self._result = kwargs
        raise _ExitJson()

    def fail_json(self, **kwargs):
        self._failed = True
        self._result = kwargs
        raise _FailJson()


def _backup_params(overrides=None):
    """Build a full module params dict for backup tests."""
    p = {
        "base_url": "https://borgui.example.com",
        "token": "test-token",
        "secret_key": None,
        "secret_key_file": None,
        "username": "admin",
        "insecure": False,
        "repository": "vault-01",
        "action": "start",
        "job_id": None,
        "wait": False,
        "wait_timeout": 3600,
        "poll_interval": 5,
    }
    if overrides:
        p.update(overrides)
    return p


# ---------------------------------------------------------------------------
# Tests for _handle_start
# ---------------------------------------------------------------------------

class TestHandleStart:
    def test_starts_backup_returns_job_id(self):
        """_handle_start triggers backup and returns job_id."""
        client = MockClient()
        client._responses["/api/repositories/"] = {"repositories": REPOS}
        client._post_resp = {"job_id": 42, "status": "pending", "message": "Backup started"}
        module = MockModule(params=_backup_params())

        with pytest.raises(_ExitJson):
            backup_mod._handle_start(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        assert module._result["job_id"] == 42
        assert module._result["status"] == "pending"
        post_calls = [c for c in client.calls if c[0] == "POST"]
        assert len(post_calls) == 1
        assert post_calls[0][2] == {"repository": "/backups/vault-01"}

    def test_fails_when_repository_missing(self):
        """_handle_start fails when repository param is missing."""
        client = MockClient()
        module = MockModule(params=_backup_params({"repository": None}))

        with pytest.raises(_FailJson):
            backup_mod._handle_start(module, client)

        assert module._failed is True
        assert "repository" in module._result["msg"]

    def test_fails_when_api_returns_no_job_id(self):
        """_handle_start fails when API does not return job_id."""
        client = MockClient()
        client._responses["/api/repositories/"] = {"repositories": REPOS}
        client._post_resp = {"status": "ok"}  # No job_id
        module = MockModule(params=_backup_params())

        with pytest.raises(_FailJson):
            backup_mod._handle_start(module, client)

        assert module._failed is True
        assert "job_id" in module._result["msg"]

    def test_check_mode_no_start(self):
        """In check mode, _handle_start reports would-start but makes no POST."""
        client = MockClient()
        client._responses["/api/repositories/"] = {"repositories": REPOS}
        module = MockModule(params=_backup_params(), check_mode=True)

        with pytest.raises(_ExitJson):
            backup_mod._handle_start(module, client)

        assert module._result["changed"] is True
        assert "would be started" in module._result["message"]
        post_calls = [c for c in client.calls if c[0] == "POST"]
        assert len(post_calls) == 0

    def test_start_with_wait_polls_until_complete(self):
        """_handle_start with wait=True polls until completed status."""
        client = MockClient()
        client._responses["/api/repositories/"] = {"repositories": REPOS}
        client._post_resp = {"job_id": 42, "status": "pending", "message": "Started"}
        client._responses["/api/backup/status/42"] = JOB_COMPLETED
        module = MockModule(params=_backup_params({"wait": True, "poll_interval": 0}))

        with pytest.raises(_ExitJson):
            backup_mod._handle_start(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        assert module._result["job_id"] == 42
        assert module._result["status"] == "completed"
        assert module._result["logs"] == "Backup done."


# ---------------------------------------------------------------------------
# Tests for _poll_until_complete
# ---------------------------------------------------------------------------

class TestPollUntilComplete:
    def test_returns_on_completed(self):
        """_poll_until_complete returns when status is completed."""
        client = MockClient()
        client._responses["/api/backup/status/42"] = JOB_COMPLETED
        module = MockModule(params=_backup_params())

        result = backup_mod._poll_until_complete(module, client, 42, timeout=10, interval=0)

        assert result["status"] == "completed"

    def test_fails_on_failed_status(self):
        """_poll_until_complete fails when status is failed."""
        client = MockClient()
        client._responses["/api/backup/status/42"] = JOB_FAILED
        module = MockModule(params=_backup_params())

        with pytest.raises(_FailJson):
            backup_mod._poll_until_complete(module, client, 42, timeout=10, interval=0)

        assert module._failed is True
        assert "failed" in module._result["msg"]

    def test_returns_on_cancelled(self):
        """_poll_until_complete returns when status is cancelled."""
        client = MockClient()
        client._responses["/api/backup/status/42"] = {"status": "cancelled"}
        module = MockModule(params=_backup_params())

        result = backup_mod._poll_until_complete(module, client, 42, timeout=10, interval=0)

        assert result["status"] == "cancelled"

    def test_timeout(self):
        """_poll_until_complete fails on timeout."""
        client = MockClient()
        client._responses["/api/backup/status/42"] = JOB_RUNNING
        module = MockModule(params=_backup_params())

        with pytest.raises(_FailJson):
            backup_mod._poll_until_complete(module, client, 42, timeout=0, interval=0)

        assert module._failed is True
        assert "Timed out" in module._result["msg"]

    def test_handles_empty_response(self):
        """_poll_until_complete handles None/empty API response."""
        client = MockClient()
        client._responses["/api/backup/status/42"] = None
        module = MockModule(params=_backup_params())

        with pytest.raises(_FailJson):
            backup_mod._poll_until_complete(module, client, 42, timeout=0, interval=0)

        assert module._failed is True


# ---------------------------------------------------------------------------
# Tests for _handle_status
# ---------------------------------------------------------------------------

class TestHandleStatus:
    def test_returns_job_status(self):
        """_handle_status returns the current job status."""
        client = MockClient()
        client._responses["/api/backup/status/42"] = JOB_RUNNING
        module = MockModule(params=_backup_params({"action": "status", "job_id": 42}))

        with pytest.raises(_ExitJson):
            backup_mod._handle_status(module, client)

        assert module._failed is False
        assert module._result["changed"] is False
        assert module._result["job_id"] == 42
        assert module._result["status"] == "running"
        assert module._result["progress"] == 45

    def test_fails_when_job_id_missing(self):
        """_handle_status fails when job_id is not provided."""
        client = MockClient()
        module = MockModule(params=_backup_params({"action": "status", "job_id": None}))

        with pytest.raises(_FailJson):
            backup_mod._handle_status(module, client)

        assert module._failed is True
        assert "job_id" in module._result["msg"]


# ---------------------------------------------------------------------------
# Tests for _handle_cancel
# ---------------------------------------------------------------------------

class TestHandleCancel:
    def test_returns_informational_message(self):
        """_handle_cancel returns informational message (no actual API call)."""
        module = MockModule(params=_backup_params({"action": "cancel", "job_id": 42}))

        with pytest.raises(_ExitJson):
            backup_mod._handle_cancel(module)

        assert module._failed is False
        assert module._result["changed"] is False
        assert module._result["job_id"] == 42
        assert "not supported" in module._result["message"]

    def test_fails_when_job_id_missing(self):
        """_handle_cancel fails when job_id is not provided."""
        module = MockModule(params=_backup_params({"action": "cancel", "job_id": None}))

        with pytest.raises(_FailJson):
            backup_mod._handle_cancel(module)

        assert module._failed is True
        assert "job_id" in module._result["msg"]


# ---------------------------------------------------------------------------
# Tests for main() via monkeypatch
# ---------------------------------------------------------------------------

class TestMain:
    def _patch_and_run(self, monkeypatch, params, check_mode, client):
        mock_module = MockModule(params=params, check_mode=check_mode)
        monkeypatch.setattr(backup_mod, "AnsibleModule", lambda **kw: mock_module)
        monkeypatch.setattr(backup_mod, "make_client", lambda p: client)
        return mock_module

    def test_main_start(self, monkeypatch):
        client = MockClient()
        client._responses["/api/repositories/"] = {"repositories": REPOS}
        client._post_resp = {"job_id": 42, "status": "pending", "message": "Started"}
        params = _backup_params()
        module = self._patch_and_run(monkeypatch, params, False, client)

        with pytest.raises(_ExitJson):
            backup_mod.main()

        assert module._result["changed"] is True
        assert module._result["job_id"] == 42

    def test_main_status(self, monkeypatch):
        client = MockClient()
        client._responses["/api/backup/status/42"] = JOB_RUNNING
        params = _backup_params({"action": "status", "job_id": 42})
        module = self._patch_and_run(monkeypatch, params, False, client)

        with pytest.raises(_ExitJson):
            backup_mod.main()

        assert module._result["changed"] is False
        assert module._result["status"] == "running"

    def test_main_cancel(self, monkeypatch):
        """main() handles cancel action without creating client."""
        params = _backup_params({"action": "cancel", "job_id": 42})
        mock_module = MockModule(params=params, check_mode=False)
        monkeypatch.setattr(backup_mod, "AnsibleModule", lambda **kw: mock_module)
        # make_client should NOT be called for cancel

        with pytest.raises(_ExitJson):
            backup_mod.main()

        assert mock_module._result["changed"] is False
        assert "not supported" in mock_module._result["message"]

    def test_main_client_error(self, monkeypatch):
        params = _backup_params()
        mock_module = MockModule(params=params, check_mode=False)
        monkeypatch.setattr(backup_mod, "AnsibleModule", lambda **kw: mock_module)

        def raise_error(p):
            raise backup_mod.BorgUIClientError("connection refused")

        monkeypatch.setattr(backup_mod, "make_client", raise_error)

        with pytest.raises(_FailJson):
            backup_mod.main()

        assert mock_module._failed is True

    def test_main_api_error(self, monkeypatch):
        """main() catches BorgUIClientError from handle functions."""
        client = MockClient()

        def raise_error(path):
            raise backup_mod.BorgUIClientError("server error")

        client.get = raise_error
        params = _backup_params()
        module = self._patch_and_run(monkeypatch, params, False, client)

        with pytest.raises(_FailJson):
            backup_mod.main()

        assert module._failed is True
        assert "API error" in module._result["msg"]


class TestBuildArgSpecBackup:
    def test_returns_dict_with_expected_keys(self):
        spec = backup_mod._build_arg_spec()
        assert "repository" in spec
        assert "action" in spec
        assert "job_id" in spec
        assert "wait" in spec
        assert "wait_timeout" in spec
        assert "poll_interval" in spec
