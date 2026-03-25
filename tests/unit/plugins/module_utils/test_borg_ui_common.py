# -*- coding: utf-8 -*-
"""Unit tests for borg_ui_common module_utils."""

import base64
import json
import sys
import os
import time
import types

import pytest

# ---------------------------------------------------------------------------
# Path manipulation — same shim as test_borg_ui_client.py
# ---------------------------------------------------------------------------
COLLECTION_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)

def _make_pkg(name):
    mod = types.ModuleType(name)
    mod.__path__ = []
    return mod

for pkg in [
    "ansible_collections",
    "ansible_collections.borgui",
    "ansible_collections.borgui.borg_ui",
    "ansible_collections.borgui.borg_ui.plugins",
    "ansible_collections.borgui.borg_ui.plugins.module_utils",
]:
    if pkg not in sys.modules:
        sys.modules[pkg] = _make_pkg(pkg)

_mu_path = os.path.join(COLLECTION_ROOT, "plugins", "module_utils")
sys.modules["ansible_collections.borgui.borg_ui.plugins.module_utils"].__path__ = [_mu_path]

import importlib.util

def _load(relpath, fullname):
    spec = importlib.util.spec_from_file_location(
        fullname,
        os.path.join(_mu_path, relpath),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = mod
    spec.loader.exec_module(mod)
    return mod

# Load client first (common imports from it), then common
_client_fullname = "ansible_collections.borgui.borg_ui.plugins.module_utils.borg_ui_client"
_common_fullname = "ansible_collections.borgui.borg_ui.plugins.module_utils.borg_ui_common"

if _client_fullname not in sys.modules:
    _load("borg_ui_client.py", _client_fullname)

common_mod = _load("borg_ui_common.py", _common_fullname)

mint_jwt = common_mod.mint_jwt
validate_auth = common_mod.validate_auth
diff_dicts = common_mod.diff_dicts
arg_spec_with_auth_and_state = common_mod.arg_spec_with_auth_and_state
AUTH_ARG_SPEC = common_mod.AUTH_ARG_SPEC
BorgUIClientError = common_mod.BorgUIClientError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_payload(token):
    """Decode the JWT payload (no signature verification)."""
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


# ---------------------------------------------------------------------------
# mint_jwt tests
# ---------------------------------------------------------------------------

class TestMintJwt:
    def test_returns_string_with_three_dot_parts(self):
        token = mint_jwt("mysecret", "admin")
        parts = token.split(".")
        assert len(parts) == 3
        assert all(part for part in parts)  # no empty segments

    def test_payload_contains_sub_claim(self):
        token = mint_jwt("mysecret", "testuser")
        payload = _decode_payload(token)
        assert payload["sub"] == "testuser"

    def test_payload_contains_iat_and_exp(self):
        before = int(time.time())
        token = mint_jwt("mysecret", "admin", ttl=3600)
        after = int(time.time())
        payload = _decode_payload(token)
        assert "exp" in payload
        # exp must be in the range [before+3600, after+3600]
        assert before + 3600 <= payload["exp"] <= after + 3600

    def test_exp_minus_iat_equals_ttl(self):
        ttl = 7200
        token = mint_jwt("mysecret", "admin", ttl=ttl)
        payload = _decode_payload(token)
        # The implementation stores only exp (not iat), but exp = now + ttl.
        # Verify that exp is approximately now + ttl (within 2s clock drift).
        now = int(time.time())
        assert abs(payload["exp"] - now - ttl) <= 2

    def test_custom_ttl(self):
        ttl = 300
        token = mint_jwt("mysecret", "admin", ttl=ttl)
        payload = _decode_payload(token)
        now = int(time.time())
        assert abs(payload["exp"] - now - ttl) <= 2

    def test_default_ttl_is_86400(self):
        token = mint_jwt("key", "admin")
        payload = _decode_payload(token)
        now = int(time.time())
        assert abs(payload["exp"] - now - 86400) <= 2

    def test_default_username_is_admin(self):
        token = mint_jwt("key")
        payload = _decode_payload(token)
        assert payload["sub"] == "admin"

    def test_different_secrets_produce_different_signatures(self):
        t1 = mint_jwt("key1", "admin")
        t2 = mint_jwt("key2", "admin")
        sig1 = t1.split(".")[2]
        sig2 = t2.split(".")[2]
        assert sig1 != sig2

    def test_different_usernames_produce_different_tokens(self):
        t1 = mint_jwt("key", "alice")
        t2 = mint_jwt("key", "bob")
        assert t1 != t2


# ---------------------------------------------------------------------------
# validate_auth tests
# ---------------------------------------------------------------------------

class TestValidateAuth:
    def test_raises_when_no_auth_provided(self):
        with pytest.raises(ValueError, match="One of token"):
            validate_auth({})

    def test_raises_when_all_auth_fields_are_none(self):
        with pytest.raises(ValueError, match="One of token"):
            validate_auth({"token": None, "secret_key": None, "secret_key_file": None})

    def test_returns_successfully_with_token(self):
        # Should not raise
        validate_auth({"token": "abc123"})

    def test_returns_none_with_token(self):
        result = validate_auth({"token": "abc123"})
        assert result is None

    def test_returns_successfully_with_secret_key(self):
        validate_auth({"secret_key": "supersecret"})

    def test_returns_successfully_with_secret_key_file(self):
        validate_auth({"secret_key_file": "/path/to/key.txt"})

    def test_raises_when_token_and_secret_key_both_provided(self):
        with pytest.raises(ValueError, match="Only one of"):
            validate_auth({"token": "t", "secret_key": "s"})

    def test_raises_when_token_and_secret_key_file_both_provided(self):
        with pytest.raises(ValueError, match="Only one of"):
            validate_auth({"token": "t", "secret_key_file": "/path"})

    def test_raises_when_secret_key_and_file_both_provided(self):
        with pytest.raises(ValueError, match="Only one of"):
            validate_auth({"secret_key": "s", "secret_key_file": "/path"})

    def test_raises_when_all_three_provided(self):
        with pytest.raises(ValueError, match="Only one of"):
            validate_auth({"token": "t", "secret_key": "s", "secret_key_file": "/p"})

    def test_error_message_lists_conflicting_params(self):
        with pytest.raises(ValueError) as exc_info:
            validate_auth({"token": "t", "secret_key": "s"})
        msg = str(exc_info.value)
        assert "token" in msg
        assert "secret_key" in msg

    def test_ignores_unrelated_keys(self):
        # Extra keys like base_url, username should not interfere
        validate_auth({"token": "abc", "base_url": "http://host", "username": "admin"})


# ---------------------------------------------------------------------------
# diff_dicts tests
# ---------------------------------------------------------------------------

class TestDiffDicts:
    def test_returns_dict_with_before_and_after_keys(self):
        result = diff_dicts({"a": 1}, {"a": 2})
        assert "before" in result
        assert "after" in result

    def test_changed_key_appears_in_both(self):
        result = diff_dicts({"name": "old"}, {"name": "new"})
        assert result["before"]["name"] == "old"
        assert result["after"]["name"] == "new"

    def test_unchanged_key_not_included(self):
        result = diff_dicts({"name": "same", "val": 1}, {"name": "same", "val": 2})
        assert "name" not in result["before"]
        assert "name" not in result["after"]
        assert "val" in result["before"]

    def test_empty_dicts_produce_empty_diff(self):
        result = diff_dicts({}, {})
        assert result == {"before": {}, "after": {}}

    def test_identical_dicts_produce_empty_diff(self):
        d = {"a": 1, "b": "hello"}
        result = diff_dicts(d, d.copy())
        assert result == {"before": {}, "after": {}}

    def test_key_added_in_after(self):
        result = diff_dicts({}, {"newkey": "val"})
        assert result["before"]["newkey"] is None
        assert result["after"]["newkey"] == "val"

    def test_key_removed_in_after(self):
        result = diff_dicts({"oldkey": "val"}, {})
        assert result["before"]["oldkey"] == "val"
        assert result["after"]["oldkey"] is None

    def test_multiple_changes_all_captured(self):
        before = {"a": 1, "b": 2, "c": 3}
        after = {"a": 10, "b": 2, "c": 30}
        result = diff_dicts(before, after)
        assert set(result["before"].keys()) == {"a", "c"}
        assert result["before"]["a"] == 1
        assert result["after"]["a"] == 10
        assert result["before"]["c"] == 3
        assert result["after"]["c"] == 30

    def test_none_values_handled(self):
        result = diff_dicts({"x": None}, {"x": "value"})
        assert result["before"]["x"] is None
        assert result["after"]["x"] == "value"

    def test_false_to_true_is_a_change(self):
        result = diff_dicts({"enabled": False}, {"enabled": True})
        assert "enabled" in result["before"]

    def test_zero_to_nonzero_is_a_change(self):
        result = diff_dicts({"count": 0}, {"count": 1})
        assert "count" in result["before"]


# ---------------------------------------------------------------------------
# arg_spec_with_auth_and_state tests
# ---------------------------------------------------------------------------

class TestArgSpecWithAuthAndState:
    def test_returns_dict(self):
        spec = arg_spec_with_auth_and_state()
        assert isinstance(spec, dict)

    def test_includes_auth_fields(self):
        spec = arg_spec_with_auth_and_state()
        for key in AUTH_ARG_SPEC:
            assert key in spec, "Missing AUTH field: {0}".format(key)

    def test_includes_state_field(self):
        spec = arg_spec_with_auth_and_state()
        assert "state" in spec
        assert spec["state"]["default"] == "present"
        assert "absent" in spec["state"]["choices"]

    def test_extra_spec_merged(self):
        extra = {"name": {"type": "str", "required": True}}
        spec = arg_spec_with_auth_and_state(**extra)
        assert "name" in spec
        assert spec["name"]["required"] is True

    def test_extra_spec_does_not_lose_auth_fields(self):
        extra = {"repo_id": {"type": "int"}}
        spec = arg_spec_with_auth_and_state(**extra)
        assert "base_url" in spec
        assert "token" in spec
        assert "repo_id" in spec

    def test_no_extra_spec_returns_auth_plus_state_only(self):
        spec = arg_spec_with_auth_and_state()
        expected_keys = set(AUTH_ARG_SPEC.keys()) | {"state"}
        assert set(spec.keys()) == expected_keys

    def test_extra_spec_can_override_defaults(self):
        # Callers may override e.g. state choices
        override = {"state": {"type": "str", "choices": ["enabled", "disabled"]}}
        spec = arg_spec_with_auth_and_state(**override)
        assert spec["state"]["choices"] == ["enabled", "disabled"]

    def test_does_not_mutate_auth_arg_spec(self):
        original_keys = set(AUTH_ARG_SPEC.keys())
        arg_spec_with_auth_and_state(extra_field={"type": "str"})
        assert set(AUTH_ARG_SPEC.keys()) == original_keys
