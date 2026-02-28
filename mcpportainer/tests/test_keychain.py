"""Tests for macOS Keychain integration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import subprocess

import pytest

from portainer_mcp.keychain import store_secret, retrieve_secret, delete_secret


# ---------------------------------------------------------------------------
# Helper: mock a successful security CLI response
# ---------------------------------------------------------------------------

def _mock_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# store_secret
# ---------------------------------------------------------------------------

class TestStoreSecret:
    def test_stores_successfully(self):
        with patch("portainer_mcp.keychain._run_security") as mock_sec:
            mock_sec.return_value = _mock_proc(returncode=0)
            store_secret("portainer-token", "mytoken")
            # Called twice: delete (cleanup) then add
            assert mock_sec.call_count == 2

    def test_raises_on_add_failure(self):
        with patch("portainer_mcp.keychain._run_security") as mock_sec:
            mock_sec.side_effect = [
                _mock_proc(returncode=0),        # delete (ok)
                _mock_proc(returncode=1, stderr="error"), # add fails
            ]
            with pytest.raises(RuntimeError, match="Keychain store failed"):
                store_secret("portainer-token", "mytoken")


# ---------------------------------------------------------------------------
# retrieve_secret
# ---------------------------------------------------------------------------

class TestRetrieveSecret:
    def test_returns_value(self):
        with patch("portainer_mcp.keychain._run_security") as mock_sec:
            mock_sec.return_value = _mock_proc(returncode=0, stdout="mytoken\n")
            result = retrieve_secret("portainer-token")
        assert result == "mytoken"

    def test_returns_none_when_not_found(self):
        with patch("portainer_mcp.keychain._run_security") as mock_sec:
            mock_sec.return_value = _mock_proc(returncode=44)
            result = retrieve_secret("portainer-token")
        assert result is None

    def test_returns_none_for_empty_value(self):
        with patch("portainer_mcp.keychain._run_security") as mock_sec:
            mock_sec.return_value = _mock_proc(returncode=0, stdout="   ")
            result = retrieve_secret("portainer-token")
        assert result is None


# ---------------------------------------------------------------------------
# delete_secret
# ---------------------------------------------------------------------------

class TestDeleteSecret:
    def test_returns_true_on_success(self):
        with patch("portainer_mcp.keychain._run_security") as mock_sec:
            mock_sec.return_value = _mock_proc(returncode=0)
            assert delete_secret("portainer-token") is True

    def test_returns_false_when_not_found(self):
        with patch("portainer_mcp.keychain._run_security") as mock_sec:
            mock_sec.return_value = _mock_proc(returncode=44)
            assert delete_secret("portainer-token") is False
