# -*- coding: utf-8 -*-
"""Unit tests for borg_ui_notification module."""

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
notif_mod = _load_source(
    "ansible_collections.borgui.borg_ui.plugins.modules.borg_ui_notification",
    os.path.join(MOD_PATH, "borg_ui_notification.py"),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOTIF_FIXTURE = {
    "id": 1,
    "name": "Slack Alerts",
    "service_url": "slack://token@channel",
    "enabled": True,
    "title_prefix": None,
    "include_job_name_in_title": False,
    "notify_on_backup_start": False,
    "notify_on_backup_success": False,
    "notify_on_backup_failure": True,
    "notify_on_restore_success": False,
    "notify_on_restore_failure": True,
    "notify_on_check_success": False,
    "notify_on_check_failure": True,
    "notify_on_schedule_failure": True,
    "monitor_all_repositories": True,
    "repository_ids": None,
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00",
}


class MockClient:
    def __init__(self):
        self.calls = []
        self._responses = {}
        self._post_resp = None
        self._put_resp = None

    def get(self, path):
        self.calls.append(("GET", path))
        return self._responses.get(path)

    def post(self, path, data=None):
        self.calls.append(("POST", path, data))
        return self._post_resp

    def put(self, path, data=None):
        self.calls.append(("PUT", path, data))
        return self._put_resp

    def delete(self, path):
        self.calls.append(("DELETE", path))
        return None


# ---------------------------------------------------------------------------
# Tests for _find_notification
# ---------------------------------------------------------------------------

class TestFindNotification:
    def test_finds_by_name(self):
        client = MockClient()
        client._responses["/api/notifications"] = [NOTIF_FIXTURE]
        result = notif_mod._find_notification_by_name(client, "Slack Alerts")
        assert result is not None
        assert result["id"] == 1

    def test_returns_none_when_not_found(self):
        client = MockClient()
        client._responses["/api/notifications"] = []
        result = notif_mod._find_notification_by_name(client, "Missing")
        assert result is None

    def test_case_sensitive_match(self):
        client = MockClient()
        client._responses["/api/notifications"] = [NOTIF_FIXTURE]
        result = notif_mod._find_notification_by_name(client, "slack alerts")  # wrong case
        assert result is None


# ---------------------------------------------------------------------------
# Tests for _needs_update
# ---------------------------------------------------------------------------

MATCHING_PARAMS = {
    "service_url": NOTIF_FIXTURE["service_url"],
    "enabled": NOTIF_FIXTURE["enabled"],
    "title_prefix": NOTIF_FIXTURE["title_prefix"],
    "include_job_name_in_title": NOTIF_FIXTURE["include_job_name_in_title"],
    "notify_on_backup_start": NOTIF_FIXTURE["notify_on_backup_start"],
    "notify_on_backup_success": NOTIF_FIXTURE["notify_on_backup_success"],
    "notify_on_backup_failure": NOTIF_FIXTURE["notify_on_backup_failure"],
    "notify_on_restore_success": NOTIF_FIXTURE["notify_on_restore_success"],
    "notify_on_restore_failure": NOTIF_FIXTURE["notify_on_restore_failure"],
    "notify_on_check_success": NOTIF_FIXTURE["notify_on_check_success"],
    "notify_on_check_failure": NOTIF_FIXTURE["notify_on_check_failure"],
    "notify_on_schedule_failure": NOTIF_FIXTURE["notify_on_schedule_failure"],
    "monitor_all_repositories": NOTIF_FIXTURE["monitor_all_repositories"],
    "repository_ids": NOTIF_FIXTURE["repository_ids"],
}


class TestNeedsUpdate:
    def test_no_change_when_identical(self):
        changed, _, _ = notif_mod._needs_update(NOTIF_FIXTURE, MATCHING_PARAMS)
        assert changed is False

    def test_detects_service_url_change(self):
        params = dict(MATCHING_PARAMS, service_url="mailto://user@smtp.example.com")
        changed, _, _ = notif_mod._needs_update(NOTIF_FIXTURE, params)
        assert changed is True

    def test_detects_enabled_change(self):
        params = dict(MATCHING_PARAMS, enabled=False)
        changed, _, _ = notif_mod._needs_update(NOTIF_FIXTURE, params)
        assert changed is True

    def test_detects_notify_flag_change(self):
        params = dict(MATCHING_PARAMS, notify_on_backup_success=True)
        changed, _, _ = notif_mod._needs_update(NOTIF_FIXTURE, params)
        assert changed is True

    def test_detects_monitor_all_change(self):
        params = dict(MATCHING_PARAMS, monitor_all_repositories=False, repository_ids=[1])
        changed, _, _ = notif_mod._needs_update(NOTIF_FIXTURE, params)
        assert changed is True


# ---------------------------------------------------------------------------
# Tests for _build_payload
# ---------------------------------------------------------------------------

class TestBuildPayload:
    def test_includes_all_configurable_fields(self):
        params = dict(MATCHING_PARAMS, name="Test")
        payload = notif_mod._build_payload(params)
        assert payload["name"] == "Test"
        assert "service_url" in payload
        assert "enabled" in payload
        assert "notify_on_backup_failure" in payload
        assert "monitor_all_repositories" in payload


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


def _notif_params(overrides=None):
    """Build a full module params dict for notification tests."""
    p = {
        "name": "Slack Alerts",
        "service_url": "slack://token@channel",
        "enabled": True,
        "title_prefix": None,
        "include_job_name_in_title": False,
        "notify_on_backup_start": False,
        "notify_on_backup_success": False,
        "notify_on_backup_failure": True,
        "notify_on_restore_success": False,
        "notify_on_restore_failure": True,
        "notify_on_check_success": False,
        "notify_on_check_failure": True,
        "notify_on_schedule_failure": True,
        "monitor_all_repositories": True,
        "repository_ids": None,
        "state": "present",
    }
    if overrides:
        p.update(overrides)
    return p


# ---------------------------------------------------------------------------
# Tests for _handle_present
# ---------------------------------------------------------------------------

class TestHandlePresent:
    def test_creates_when_not_found(self):
        """_handle_present creates notification when it does not exist."""
        client = MockClient()
        client._responses["/api/notifications"] = []
        client._post_resp = {"notification": {"id": 5, "name": "Slack Alerts"}}
        module = MockModule(params=_notif_params())

        with pytest.raises(_ExitJson):
            notif_mod._handle_present(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        assert module._result["notification"]["id"] == 5
        post_calls = [c for c in client.calls if c[0] == "POST"]
        assert len(post_calls) == 1

    def test_no_change_when_identical(self):
        """_handle_present reports no change when existing matches desired."""
        client = MockClient()
        client._responses["/api/notifications"] = [NOTIF_FIXTURE]
        module = MockModule(params=_notif_params())

        with pytest.raises(_ExitJson):
            notif_mod._handle_present(module, client)

        assert module._failed is False
        assert module._result["changed"] is False
        assert module._result["notification"] == NOTIF_FIXTURE

    def test_updates_when_different(self):
        """_handle_present updates notification when existing differs from desired."""
        client = MockClient()
        client._responses["/api/notifications"] = [NOTIF_FIXTURE]
        updated = dict(NOTIF_FIXTURE, enabled=False)
        client._put_resp = {"notification": updated}
        module = MockModule(params=_notif_params({"enabled": False}))

        with pytest.raises(_ExitJson):
            notif_mod._handle_present(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        assert module._result["diff"]["before"]["enabled"] is True
        assert module._result["diff"]["after"]["enabled"] is False
        put_calls = [c for c in client.calls if c[0] == "PUT"]
        assert len(put_calls) == 1

    def test_check_mode_create(self):
        """In check mode, _handle_present reports would-create but makes no POST."""
        client = MockClient()
        client._responses["/api/notifications"] = []
        module = MockModule(params=_notif_params(), check_mode=True)

        with pytest.raises(_ExitJson):
            notif_mod._handle_present(module, client)

        assert module._result["changed"] is True
        post_calls = [c for c in client.calls if c[0] == "POST"]
        assert len(post_calls) == 0

    def test_check_mode_update(self):
        """In check mode, _handle_present reports would-update but makes no PUT."""
        client = MockClient()
        client._responses["/api/notifications"] = [NOTIF_FIXTURE]
        module = MockModule(params=_notif_params({"enabled": False}), check_mode=True)

        with pytest.raises(_ExitJson):
            notif_mod._handle_present(module, client)

        assert module._result["changed"] is True
        put_calls = [c for c in client.calls if c[0] == "PUT"]
        assert len(put_calls) == 0

    def test_check_mode_no_change(self):
        """In check mode with no differences, reports changed=False."""
        client = MockClient()
        client._responses["/api/notifications"] = [NOTIF_FIXTURE]
        module = MockModule(params=_notif_params(), check_mode=True)

        with pytest.raises(_ExitJson):
            notif_mod._handle_present(module, client)

        assert module._result["changed"] is False

    def test_fails_when_service_url_missing(self):
        """_handle_present fails when service_url is not provided."""
        client = MockClient()
        module = MockModule(params=_notif_params({"service_url": None}))

        with pytest.raises(_FailJson):
            notif_mod._handle_present(module, client)

        assert module._failed is True
        assert "service_url" in module._result["msg"]

    def test_create_handles_missing_api_response(self):
        """_handle_present handles API not returning notification details on create."""
        client = MockClient()
        client._responses["/api/notifications"] = []
        client._post_resp = {}  # No "notification" key
        module = MockModule(params=_notif_params())

        with pytest.raises(_ExitJson):
            notif_mod._handle_present(module, client)

        assert module._result["changed"] is True
        assert "_warning" in module._result["notification"]

    def test_handles_dict_response_format(self):
        """_handle_present handles API returning dict with notifications key."""
        client = MockClient()
        client._responses["/api/notifications"] = {"notifications": [NOTIF_FIXTURE]}
        module = MockModule(params=_notif_params())

        with pytest.raises(_ExitJson):
            notif_mod._handle_present(module, client)

        assert module._failed is False
        assert module._result["changed"] is False


# ---------------------------------------------------------------------------
# Tests for _handle_absent
# ---------------------------------------------------------------------------

class TestHandleAbsent:
    def test_no_change_when_not_found(self):
        """_handle_absent reports no change when notification does not exist."""
        client = MockClient()
        client._responses["/api/notifications"] = []
        module = MockModule(params=_notif_params({"state": "absent"}))

        with pytest.raises(_ExitJson):
            notif_mod._handle_absent(module, client)

        assert module._failed is False
        assert module._result["changed"] is False
        assert module._result["notification"] is None

    def test_deletes_when_found(self):
        """_handle_absent deletes notification when it exists."""
        client = MockClient()
        client._responses["/api/notifications"] = [NOTIF_FIXTURE]
        module = MockModule(params=_notif_params({"state": "absent"}))

        with pytest.raises(_ExitJson):
            notif_mod._handle_absent(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        assert module._result["notification"] is None
        delete_calls = [c for c in client.calls if c[0] == "DELETE"]
        assert len(delete_calls) == 1
        assert "/api/notifications/1" in delete_calls[0][1]

    def test_check_mode_no_delete(self):
        """In check mode, _handle_absent reports would-delete but makes no API call."""
        client = MockClient()
        client._responses["/api/notifications"] = [NOTIF_FIXTURE]
        module = MockModule(params=_notif_params({"state": "absent"}), check_mode=True)

        with pytest.raises(_ExitJson):
            notif_mod._handle_absent(module, client)

        assert module._result["changed"] is True
        delete_calls = [c for c in client.calls if c[0] == "DELETE"]
        assert len(delete_calls) == 0

    def test_check_mode_not_found(self):
        """In check mode, _handle_absent reports no change when not found."""
        client = MockClient()
        client._responses["/api/notifications"] = []
        module = MockModule(params=_notif_params({"state": "absent"}), check_mode=True)

        with pytest.raises(_ExitJson):
            notif_mod._handle_absent(module, client)

        assert module._result["changed"] is False


# ---------------------------------------------------------------------------
# Tests for main() via monkeypatch
# ---------------------------------------------------------------------------

class TestMain:
    def _patch_and_run(self, monkeypatch, params, check_mode, client):
        mock_module = MockModule(params=params, check_mode=check_mode)
        monkeypatch.setattr(notif_mod, "AnsibleModule", lambda **kw: mock_module)
        monkeypatch.setattr(notif_mod, "make_client", lambda p: client)
        return mock_module

    def test_main_present_create(self, monkeypatch):
        client = MockClient()
        client._responses["/api/notifications"] = []
        client._post_resp = {"notification": {"id": 5, "name": "Slack Alerts"}}
        params = _notif_params()
        module = self._patch_and_run(monkeypatch, params, False, client)

        with pytest.raises(_ExitJson):
            notif_mod.main()

        assert module._result["changed"] is True

    def test_main_present_no_change(self, monkeypatch):
        client = MockClient()
        client._responses["/api/notifications"] = [NOTIF_FIXTURE]
        params = _notif_params()
        module = self._patch_and_run(monkeypatch, params, False, client)

        with pytest.raises(_ExitJson):
            notif_mod.main()

        assert module._result["changed"] is False

    def test_main_absent_deletes(self, monkeypatch):
        client = MockClient()
        client._responses["/api/notifications"] = [NOTIF_FIXTURE]
        params = _notif_params({"state": "absent"})
        module = self._patch_and_run(monkeypatch, params, False, client)

        with pytest.raises(_ExitJson):
            notif_mod.main()

        assert module._result["changed"] is True

    def test_main_client_error(self, monkeypatch):
        params = _notif_params()
        mock_module = MockModule(params=params, check_mode=False)
        monkeypatch.setattr(notif_mod, "AnsibleModule", lambda **kw: mock_module)

        def raise_error(p):
            raise notif_mod.BorgUIClientError("connection refused")

        monkeypatch.setattr(notif_mod, "make_client", raise_error)

        with pytest.raises(_FailJson):
            notif_mod.main()

        assert mock_module._failed is True

    def test_main_api_error(self, monkeypatch):
        """main() catches BorgUIClientError from handle functions."""
        client = MockClient()

        def raise_error(path):
            raise notif_mod.BorgUIClientError("server error")

        client.get = raise_error
        params = _notif_params()
        module = self._patch_and_run(monkeypatch, params, False, client)

        with pytest.raises(_FailJson):
            notif_mod.main()

        assert module._failed is True
        assert "API error" in module._result["msg"]


# ---------------------------------------------------------------------------
# Tests for _make_client_params and _build_arg_spec
# ---------------------------------------------------------------------------

class TestMakeClientParams:
    def test_maps_api_username_to_username(self):
        params = dict(_notif_params(), api_username="myuser")
        result = notif_mod._make_client_params(params)
        assert result["username"] == "myuser"
        assert "api_username" not in result


class TestBuildArgSpecNotification:
    def test_returns_dict_with_expected_keys(self):
        spec = notif_mod._build_arg_spec()
        assert "name" in spec
        assert "service_url" in spec
        assert "enabled" in spec
        assert "notify_on_backup_failure" in spec
        assert "monitor_all_repositories" in spec
