# -*- coding: utf-8 -*-
"""Unit tests for borg_ui_connection module."""

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
conn_mod = _load_source(
    "ansible_collections.borgui.borg_ui.plugins.modules.borg_ui_connection",
    os.path.join(MOD_PATH, "borg_ui_connection.py"),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CONN_FIXTURE = {
    "id": 1,
    "ssh_key_id": 2,
    "ssh_key_name": "my-ssh-key",
    "host": "backup-server.example.com",
    "username": "ansible",
    "port": 22,
    "use_sftp_mode": False,
    "use_sudo": False,
    "default_path": "/opt",
    "ssh_path_prefix": "",
    "mount_point": "",
    "status": "connected",
    "error_message": None,
}

REPOS_FIXTURE = [
    {"id": 10, "name": "vault-01", "source_ssh_connection_id": 1},
    {"id": 11, "name": "gitlab-01", "source_ssh_connection_id": None},
]


class MockClient:
    def __init__(self):
        self.calls = []
        self._responses = {}
        self._put_resp = None
        self._post_resp = None

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
# Tests for _find_connection
# ---------------------------------------------------------------------------

class TestFindConnection:
    def test_finds_by_host_user_port(self):
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {
            "connections": [CONN_FIXTURE]
        }
        result = conn_mod._find_connection(client, "backup-server.example.com", "ansible", 22)
        assert result is not None
        assert result["id"] == 1

    def test_returns_none_for_wrong_user(self):
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {
            "connections": [CONN_FIXTURE]
        }
        result = conn_mod._find_connection(client, "backup-server.example.com", "root", 22)
        assert result is None

    def test_returns_none_for_wrong_port(self):
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {
            "connections": [CONN_FIXTURE]
        }
        result = conn_mod._find_connection(client, "backup-server.example.com", "ansible", 2222)
        assert result is None

    def test_returns_none_for_wrong_host(self):
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {
            "connections": [CONN_FIXTURE]
        }
        result = conn_mod._find_connection(client, "other.example.com", "ansible", 22)
        assert result is None

    def test_returns_none_when_no_connections(self):
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": []}
        result = conn_mod._find_connection(client, "backup-server.example.com", "ansible", 22)
        assert result is None


# ---------------------------------------------------------------------------
# Tests for _needs_update
# ---------------------------------------------------------------------------

def _conn_desired(overrides=None):
    """Build a desired-state dict for connection _needs_update."""
    d = {
        "host": CONN_FIXTURE["host"],
        "username": CONN_FIXTURE["username"],
        "port": CONN_FIXTURE["port"],
        "use_sftp_mode": CONN_FIXTURE["use_sftp_mode"],
        "use_sudo": CONN_FIXTURE["use_sudo"],
        "default_path": CONN_FIXTURE["default_path"],
        "ssh_path_prefix": CONN_FIXTURE["ssh_path_prefix"],
        "mount_point": CONN_FIXTURE["mount_point"],
    }
    if overrides:
        d.update(overrides)
    return d


class TestNeedsUpdate:
    def test_no_change_when_same(self):
        changed, _, _ = conn_mod._needs_update(CONN_FIXTURE, _conn_desired())
        assert changed is False

    def test_detects_sftp_change(self):
        changed, _, _ = conn_mod._needs_update(CONN_FIXTURE, _conn_desired({"use_sftp_mode": True}))
        assert changed is True

    def test_detects_default_path_change(self):
        changed, _, _ = conn_mod._needs_update(CONN_FIXTURE, _conn_desired({"default_path": "/home"}))
        assert changed is True

    def test_detects_sudo_change(self):
        changed, _, _ = conn_mod._needs_update(CONN_FIXTURE, _conn_desired({"use_sudo": True}))
        assert changed is True

    def test_no_change_when_sudo_matches(self):
        changed, _, _ = conn_mod._needs_update(CONN_FIXTURE, _conn_desired({"use_sudo": False}))
        assert changed is False


# ---------------------------------------------------------------------------
# Tests for _build_payload
# ---------------------------------------------------------------------------

class TestBuildPayload:
    def test_includes_use_sudo(self):
        params = {
            "host": "db-01.example.com",
            "ssh_username": "ansible",
            "port": 22,
            "use_sftp_mode": False,
            "use_sudo": True,
            "default_path": "/opt",
            "ssh_path_prefix": "",
            "mount_point": "",
        }
        payload = conn_mod._build_payload(params)
        assert payload["use_sudo"] is True

    def test_use_sudo_defaults_false(self):
        params = {
            "host": "web-01.example.com",
            "ssh_username": "ansible",
            "port": 22,
            "use_sftp_mode": False,
            "use_sudo": False,
            "default_path": "/opt",
            "ssh_path_prefix": "",
            "mount_point": "",
        }
        payload = conn_mod._build_payload(params)
        assert payload["use_sudo"] is False


# ---------------------------------------------------------------------------
# Tests for _get_repos_using_connection
# ---------------------------------------------------------------------------

class TestGetReferencingRepos:
    def test_finds_repos_referencing_connection(self):
        client = MockClient()
        client._responses["/api/repositories/"] = {"repositories": REPOS_FIXTURE}
        result = conn_mod._get_referencing_repos(client, connection_id=1)
        assert len(result) == 1
        assert result[0]["name"] == "vault-01"

    def test_returns_empty_when_none_reference(self):
        client = MockClient()
        client._responses["/api/repositories/"] = {
            "repositories": [{"id": 11, "name": "gitlab-01", "source_ssh_connection_id": None}]
        }
        result = conn_mod._get_referencing_repos(client, connection_id=1)
        assert result == []


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


def _conn_params(overrides=None):
    """Build a full module params dict for connection tests."""
    p = {
        "host": "backup-server.example.com",
        "ssh_username": "ansible",
        "port": 22,
        "use_sftp_mode": False,
        "use_sudo": False,
        "default_path": "/opt",
        "ssh_path_prefix": "",
        "mount_point": "",
        "cascade": False,
        "state": "present",
    }
    if overrides:
        p.update(overrides)
    return p


# ---------------------------------------------------------------------------
# Tests for _get_system_key_id
# ---------------------------------------------------------------------------

class TestGetSystemKeyId:
    def test_returns_key_id_when_exists(self):
        client = MockClient()
        client._responses["/api/ssh-keys/system-key"] = {
            "exists": True, "ssh_key": {"id": 7, "name": "system-key"}
        }
        assert conn_mod._get_system_key_id(client) == 7

    def test_returns_none_when_no_system_key(self):
        client = MockClient()
        client._responses["/api/ssh-keys/system-key"] = {"exists": False}
        assert conn_mod._get_system_key_id(client) is None

    def test_returns_none_when_response_empty(self):
        client = MockClient()
        client._responses["/api/ssh-keys/system-key"] = None
        assert conn_mod._get_system_key_id(client) is None


# ---------------------------------------------------------------------------
# Tests for _handle_present
# ---------------------------------------------------------------------------

class TestHandlePresent:
    def test_fails_when_no_system_key(self):
        """_handle_present fails when connection not found and no system key exists."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": []}
        client._responses["/api/ssh-keys/system-key"] = {"exists": False}
        module = MockModule(params=_conn_params())

        with pytest.raises(_FailJson):
            conn_mod._handle_present(module, client)

        assert module._failed is True
        assert "No system SSH key" in module._result["msg"]

    def test_creates_connection_when_not_found(self):
        """_handle_present creates connection via system key when not found."""
        client = MockClient()
        # First call: connection not found; after creation: connection found
        get_call_count = {"n": 0}
        orig_get = client.get

        def get_with_state(path):
            if path == "/api/ssh-keys/connections":
                get_call_count["n"] += 1
                if get_call_count["n"] == 1:
                    return {"connections": []}
                return {"connections": [CONN_FIXTURE]}
            return orig_get(path)

        client.get = get_with_state
        client._responses["/api/ssh-keys/system-key"] = {
            "exists": True, "ssh_key": {"id": 5}
        }
        module = MockModule(params=_conn_params())

        with pytest.raises(_ExitJson):
            conn_mod._handle_present(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        assert module._result["connection"]["id"] == 1
        # Verify POST was called to test-connection
        post_calls = [c for c in client.calls if c[0] == "POST"]
        assert len(post_calls) == 1
        assert "/api/ssh-keys/5/test-connection" in post_calls[0][1]

    def test_creates_and_updates_additional_fields(self):
        """_handle_present creates then updates when extra fields differ from defaults."""
        client = MockClient()
        # Connection returned after creation has use_sudo=False (default)
        created_conn = dict(CONN_FIXTURE, use_sudo=False)
        get_call_count = {"n": 0}

        def get_with_state(path):
            if path == "/api/ssh-keys/connections":
                get_call_count["n"] += 1
                if get_call_count["n"] == 1:
                    return {"connections": []}
                # After creation, return connection with defaults
                return {"connections": [created_conn]}
            if path == "/api/ssh-keys/system-key":
                return {"exists": True, "ssh_key": {"id": 5}}
            return None

        client.get = get_with_state
        client._put_resp = {"connection": dict(CONN_FIXTURE, use_sudo=True)}
        module = MockModule(params=_conn_params({"use_sudo": True}))

        with pytest.raises(_ExitJson):
            conn_mod._handle_present(module, client)

        assert module._result["changed"] is True
        # Verify both POST (create) and PUT (update) were called
        post_calls = [c for c in client.calls if c[0] == "POST"]
        put_calls = [c for c in client.calls if c[0] == "PUT"]
        assert len(post_calls) == 1
        assert len(put_calls) == 1

    def test_create_check_mode(self):
        """In check mode, _handle_present reports would-create without API calls."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": []}
        client._responses["/api/ssh-keys/system-key"] = {
            "exists": True, "ssh_key": {"id": 5}
        }
        module = MockModule(params=_conn_params(), check_mode=True)

        with pytest.raises(_ExitJson):
            conn_mod._handle_present(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        assert module._result["diff"]["before"] == {}
        # No POST or PUT should have been made
        post_calls = [c for c in client.calls if c[0] == "POST"]
        put_calls = [c for c in client.calls if c[0] == "PUT"]
        assert len(post_calls) == 0
        assert len(put_calls) == 0

    def test_no_change_when_identical(self):
        """_handle_present reports no change when existing matches desired."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        module = MockModule(params=_conn_params())

        with pytest.raises(_ExitJson):
            conn_mod._handle_present(module, client)

        assert module._failed is False
        assert module._result["changed"] is False
        assert module._result["connection"] == CONN_FIXTURE

    def test_updates_when_different(self):
        """_handle_present updates connection when existing differs from desired."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        client._put_resp = {"connection": dict(CONN_FIXTURE, use_sftp_mode=True)}
        module = MockModule(params=_conn_params({"use_sftp_mode": True}))

        with pytest.raises(_ExitJson):
            conn_mod._handle_present(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        assert module._result["diff"]["before"]["use_sftp_mode"] is False
        assert module._result["diff"]["after"]["use_sftp_mode"] is True
        put_calls = [c for c in client.calls if c[0] == "PUT"]
        assert len(put_calls) == 1
        assert "/api/ssh-keys/connections/1" in put_calls[0][1]

    def test_check_mode_no_mutation(self):
        """In check mode, _handle_present reports would-change but makes no PUT."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        module = MockModule(params=_conn_params({"use_sftp_mode": True}), check_mode=True)

        with pytest.raises(_ExitJson):
            conn_mod._handle_present(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        put_calls = [c for c in client.calls if c[0] == "PUT"]
        assert len(put_calls) == 0

    def test_check_mode_no_change(self):
        """In check mode with no differences, reports changed=False."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        module = MockModule(params=_conn_params(), check_mode=True)

        with pytest.raises(_ExitJson):
            conn_mod._handle_present(module, client)

        assert module._result["changed"] is False

    def test_update_sudo_field(self):
        """_handle_present detects and updates use_sudo change."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        client._put_resp = {"connection": dict(CONN_FIXTURE, use_sudo=True)}
        module = MockModule(params=_conn_params({"use_sudo": True}))

        with pytest.raises(_ExitJson):
            conn_mod._handle_present(module, client)

        assert module._result["changed"] is True
        assert module._result["diff"]["after"]["use_sudo"] is True


# ---------------------------------------------------------------------------
# Tests for _handle_absent
# ---------------------------------------------------------------------------

class TestHandleAbsent:
    def test_no_change_when_not_found(self):
        """_handle_absent reports no change when connection does not exist."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": []}
        module = MockModule(params=_conn_params({"state": "absent"}))

        with pytest.raises(_ExitJson):
            conn_mod._handle_absent(module, client)

        assert module._failed is False
        assert module._result["changed"] is False
        assert module._result["connection"] is None

    def test_deletes_when_found_no_refs(self):
        """_handle_absent deletes connection when it exists and has no references."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        client._responses["/api/repositories/"] = {"repositories": []}
        module = MockModule(params=_conn_params({"state": "absent"}))

        with pytest.raises(_ExitJson):
            conn_mod._handle_absent(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        assert module._result["connection"] is None
        delete_calls = [c for c in client.calls if c[0] == "DELETE"]
        assert len(delete_calls) == 1

    def test_fails_when_refs_exist_no_cascade(self):
        """_handle_absent fails when repos reference connection and cascade=False."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        client._responses["/api/repositories/"] = {"repositories": REPOS_FIXTURE}
        module = MockModule(params=_conn_params({"state": "absent", "cascade": False}))

        with pytest.raises(_FailJson):
            conn_mod._handle_absent(module, client)

        assert module._failed is True
        assert "referenced by" in module._result["msg"]
        assert "vault-01" in module._result["msg"]

    def test_deletes_when_refs_exist_cascade_true(self):
        """_handle_absent deletes connection when cascade=True even with references."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        client._responses["/api/repositories/"] = {"repositories": REPOS_FIXTURE}
        module = MockModule(params=_conn_params({"state": "absent", "cascade": True}))

        with pytest.raises(_ExitJson):
            conn_mod._handle_absent(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        delete_calls = [c for c in client.calls if c[0] == "DELETE"]
        assert len(delete_calls) == 1

    def test_check_mode_no_delete(self):
        """In check mode, _handle_absent reports would-delete but makes no API call."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        client._responses["/api/repositories/"] = {"repositories": []}
        module = MockModule(params=_conn_params({"state": "absent"}), check_mode=True)

        with pytest.raises(_ExitJson):
            conn_mod._handle_absent(module, client)

        assert module._failed is False
        assert module._result["changed"] is True
        delete_calls = [c for c in client.calls if c[0] == "DELETE"]
        assert len(delete_calls) == 0

    def test_check_mode_not_found(self):
        """In check mode, _handle_absent reports no change when not found."""
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": []}
        module = MockModule(params=_conn_params({"state": "absent"}), check_mode=True)

        with pytest.raises(_ExitJson):
            conn_mod._handle_absent(module, client)

        assert module._result["changed"] is False


# ---------------------------------------------------------------------------
# Tests for main() via monkeypatch
# ---------------------------------------------------------------------------

class TestMain:
    def _patch_and_run(self, monkeypatch, params, check_mode, client):
        mock_module = MockModule(params=params, check_mode=check_mode)
        monkeypatch.setattr(conn_mod, "AnsibleModule", lambda **kw: mock_module)
        monkeypatch.setattr(conn_mod, "_make_client", lambda p: client)
        return mock_module

    def test_main_present_no_change(self, monkeypatch):
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        params = _conn_params()
        module = self._patch_and_run(monkeypatch, params, False, client)

        with pytest.raises(_ExitJson):
            conn_mod.main()

        assert module._result["changed"] is False

    def test_main_present_update(self, monkeypatch):
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        client._put_resp = {"connection": dict(CONN_FIXTURE, use_sftp_mode=True)}
        params = _conn_params({"use_sftp_mode": True})
        module = self._patch_and_run(monkeypatch, params, False, client)

        with pytest.raises(_ExitJson):
            conn_mod.main()

        assert module._result["changed"] is True

    def test_main_absent_deletes(self, monkeypatch):
        client = MockClient()
        client._responses["/api/ssh-keys/connections"] = {"connections": [CONN_FIXTURE]}
        client._responses["/api/repositories/"] = {"repositories": []}
        params = _conn_params({"state": "absent"})
        module = self._patch_and_run(monkeypatch, params, False, client)

        with pytest.raises(_ExitJson):
            conn_mod.main()

        assert module._result["changed"] is True

    def test_main_client_error(self, monkeypatch):
        params = _conn_params()
        mock_module = MockModule(params=params, check_mode=False)
        monkeypatch.setattr(conn_mod, "AnsibleModule", lambda **kw: mock_module)
        monkeypatch.setattr(conn_mod, "_make_client", lambda p: (_ for _ in ()).throw(
            conn_mod.BorgUIClientError("connection refused")
        ))

        with pytest.raises(_FailJson):
            conn_mod.main()

        assert mock_module._failed is True

    def test_main_api_error(self, monkeypatch):
        """main() catches BorgUIClientError from handle functions."""
        client = MockClient()
        # Force an error during _find_connection
        def raise_error(path):
            raise conn_mod.BorgUIClientError("server error")
        client.get = raise_error

        params = _conn_params()
        module = self._patch_and_run(monkeypatch, params, False, client)

        with pytest.raises(_FailJson):
            conn_mod.main()

        assert module._failed is True
        assert "API error" in module._result["msg"]


# ---------------------------------------------------------------------------
# Tests for _build_arg_spec and _make_client
# ---------------------------------------------------------------------------

class TestBuildArgSpec:
    def test_returns_dict_with_expected_keys(self):
        spec = conn_mod._build_arg_spec()
        assert "host" in spec
        assert "ssh_username" in spec
        assert "api_username" in spec
        assert "port" in spec
        assert "use_sftp_mode" in spec
        assert "use_sudo" in spec
        assert "cascade" in spec
        # Ensure 'username' was renamed to 'api_username'
        assert "username" not in spec
