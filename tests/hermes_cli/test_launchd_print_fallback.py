# -*- coding: utf-8 -*-
"""``launchctl list`` is unusable on some macOS hosts — pin the print fallback.

Affected hosts (e.g. macOS 26/27 per-user domains) answer ``launchctl list`` with
rc 1 and empty output for *every* label, including ones launchd actively
supervises. List-only probes then read as "unsupervised": ``hermes gateway
status`` printed "Gateway service is not loaded", ``_is_service_running()``
returned False for a live supervised service, and ``_launchd_degrade_or_raise``
lost its second guard — which is what let a kickstart failure silently rewrite
the unsupported-marker and fork a detached second gateway.

These tests pin three things only: the PID probe's print fallback, the status
page's wording, and the registered-vs-running split. No refactoring.
"""
import os
import subprocess
from unittest import mock

import pytest

from hermes_cli import gateway as gw
from hermes_cli import gateway_launchd as gl

# launchd/POSIX helpers — never invoked on Windows.
pytestmark = pytest.mark.platforms("macos")

LABEL = "ai.hermes.gateway"


class _FakeResult:
    """Stand-in for ``subprocess.CompletedProcess``; only rc/stdout are read."""

    def __init__(self, returncode=0, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def _list_unusable(*_args, **_kwargs):
    """Every ``launchctl list`` call on an affected host: rc 1, no output."""
    return _FakeResult(returncode=1, stdout="")


def _domain():
    return f"gui/{os.getuid()}"  # windows-footgun: ok — platforms("macos") file


def test_supervised_pid_falls_back_to_print_when_list_is_unusable():
    """list rc=1 + empty stdout, print state=running pid=4321 -> 4321."""
    with mock.patch.object(gl.subprocess, "run", side_effect=_list_unusable), mock.patch.object(
        gw, "_locate_launchd_gateway_service", return_value=(_domain(), 4321)
    ):
        assert gl._launchctl_supervised_pid(LABEL) == 4321


def test_supervised_pid_stays_none_when_print_reports_no_process():
    """A domain alone proves registration, not a live process — never invent a PID."""
    with mock.patch.object(gl.subprocess, "run", side_effect=_list_unusable), mock.patch.object(
        gw, "_locate_launchd_gateway_service", return_value=(_domain(), None)
    ):
        assert gl._launchctl_supervised_pid(LABEL) is None


def test_supervised_pid_swallows_print_timeout():
    """A wedged print probe is 'unknown', not a crash: fall back to the old None."""
    with mock.patch.object(gl.subprocess, "run", side_effect=_list_unusable), mock.patch.object(
        gw, "_locate_launchd_gateway_service", side_effect=subprocess.TimeoutExpired("launchctl", 5)
    ):
        assert gl._launchctl_supervised_pid(LABEL) is None


def test_status_reports_supervised_and_never_alongside_detached(capsys, tmp_path):
    plist = tmp_path / f"{LABEL}.plist"
    plist.write_text("<plist></plist>", encoding="utf-8")
    with (
        mock.patch.object(gl.subprocess, "run", side_effect=_list_unusable),
        mock.patch.object(gw, "_locate_launchd_gateway_service", return_value=(_domain(), 4321)),
        mock.patch.object(gw, "get_launchd_label", return_value=LABEL),
        mock.patch.object(gw, "get_launchd_plist_path", return_value=plist),
        mock.patch.object(gw, "launchd_plist_is_current", return_value=True),
        mock.patch.object(gw, "_launchd_unsupported_marker_exists", return_value=False),
        # The gateway's own runtime PID, deliberately != the supervising PID 4321:
        # launchd supervises a wrapper that execs the gateway, so they differ by design.
        mock.patch("gateway.status.get_running_pid", return_value=12883),
    ):
        gl.launchd_status()
    out = capsys.readouterr().out
    assert "✓ Gateway is supervised by launchd (PID 4321)" in out
    assert "not loaded" not in out
    assert "etached" not in out


def test_is_service_running_false_when_registered_but_not_running(tmp_path):
    """Registered-but-idle must read as NOT running (the old list rc=0 said True)."""
    plist = tmp_path / f"{LABEL}.plist"
    plist.write_text("<plist></plist>", encoding="utf-8")
    with (
        mock.patch.object(gw, "_locate_launchd_gateway_service", return_value=(_domain(), None)),
        mock.patch.object(gw, "get_launchd_label", return_value=LABEL),
        mock.patch.object(gw, "get_launchd_plist_path", return_value=plist),
        mock.patch.object(gw, "is_macos", return_value=True),
        mock.patch.object(gw, "supports_systemd_services", return_value=False),
    ):
        assert gw._is_service_running() is False


def test_is_service_running_true_when_print_reports_a_pid(tmp_path):
    plist = tmp_path / f"{LABEL}.plist"
    plist.write_text("<plist></plist>", encoding="utf-8")
    with (
        mock.patch.object(gw, "_locate_launchd_gateway_service", return_value=(_domain(), 4321)),
        mock.patch.object(gw, "get_launchd_label", return_value=LABEL),
        mock.patch.object(gw, "get_launchd_plist_path", return_value=plist),
        mock.patch.object(gw, "is_macos", return_value=True),
        mock.patch.object(gw, "supports_systemd_services", return_value=False),
    ):
        assert gw._is_service_running() is True
