# -*- coding: utf-8 -*-
# Copyright (c) borg-ui contributors
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Shared argument specs and helpers for borgui.borg_ui Ansible modules."""

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import json
import time
import hmac
import hashlib
import base64


# ---------------------------------------------------------------------------
# JWT minting — single source of truth
# ---------------------------------------------------------------------------

def mint_jwt(secret_key, username="admin", ttl=86400):
    """Mint a short-lived HS256 JWT using the borg-ui SECRET_KEY.

    Replicates the logic in app/core/security.py::create_access_token.
    Uses only the stdlib — no PyJWT or python-jose required.

    :param secret_key: The borg-ui SECRET_KEY string (or bytes).
    :param username: Username to embed in the ``sub`` claim (default: ``admin``).
    :param ttl: Token lifetime in seconds (default: 86400 = 24 hours).
    :returns: Signed JWT string.
    """

    def _b64url(data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")))
    exp = int(time.time()) + ttl
    payload = _b64url(json.dumps({"sub": username, "exp": exp}, separators=(",", ":")))

    signing_input = "{0}.{1}".format(header, payload).encode("utf-8")
    secret = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
    sig = hmac.new(secret, signing_input, hashlib.sha256).digest()

    return "{0}.{1}.{2}".format(header, payload, _b64url(sig))


# ---------------------------------------------------------------------------
# Re-export BorgUIClientError so callers can import it from here.
# This import is placed after mint_jwt to avoid a circular import:
# borg_ui_client imports mint_jwt from this module, so mint_jwt must be
# fully defined before borg_ui_client is loaded.
# ---------------------------------------------------------------------------

from ansible_collections.borgui.borg_ui.plugins.module_utils.borg_ui_client import (  # noqa: E402
    BorgUIClientError,
)

# ---------------------------------------------------------------------------
# Shared argument spec fragments
# ---------------------------------------------------------------------------

AUTH_ARG_SPEC = dict(
    base_url=dict(type="str", required=True),
    token=dict(type="str", no_log=True),
    secret_key=dict(type="str", no_log=True),
    secret_key_file=dict(type="path"),
    username=dict(type="str", default="admin"),
    insecure=dict(type="bool", default=False),
)

COMMON_ARG_SPEC = dict(
    state=dict(type="str", default="present", choices=["present", "absent"]),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validate_auth(params):
    """Ensure exactly one of token/secret_key/secret_key_file is provided.

    :raises ValueError: with an actionable message on failure.
    """
    provided = [
        k for k in ("token", "secret_key", "secret_key_file")
        if params.get(k)
    ]
    if not provided:
        raise ValueError(
            "One of token, secret_key, or secret_key_file must be provided"
        )
    if len(provided) > 1:
        raise ValueError(
            "Only one of token, secret_key, or secret_key_file may be provided "
            "(got: {0})".format(", ".join(provided))
        )


def make_client(params):
    """Build and return a configured :class:`BorgUIClient`.

    :param params: Module params dict.
    :returns: :class:`BorgUIClient`
    :raises ValueError: if auth params are invalid.
    """
    # Deferred import to avoid a circular dependency at module load time:
    # borg_ui_client imports mint_jwt from this module, so we must not
    # import BorgUIClient at the top of this file.
    from ansible_collections.borgui.borg_ui.plugins.module_utils.borg_ui_client import (
        BorgUIClient,
    )
    validate_auth(params)
    return BorgUIClient(
        base_url=params["base_url"],
        token=params.get("token"),
        secret_key=params.get("secret_key"),
        secret_key_file=params.get("secret_key_file"),
        username=params.get("username", "admin"),
        insecure=params.get("insecure", False),
    )


def diff_dicts(before, after):
    """Return a diff dict ``{before: ..., after: ...}`` for changed keys only.

    Both dicts are expected to contain the same top-level keys.
    """
    changed_before = {}
    changed_after = {}
    for key in set(list(before.keys()) + list(after.keys())):
        bv = before.get(key)
        av = after.get(key)
        if bv != av:
            changed_before[key] = bv
            changed_after[key] = av
    return {"before": changed_before, "after": changed_after}


def arg_spec_with_auth_and_state(**extra):
    """Return a merged arg_spec containing AUTH + COMMON + any extras."""
    spec = {}
    spec.update(AUTH_ARG_SPEC)
    spec.update(COMMON_ARG_SPEC)
    spec.update(extra)
    return spec
