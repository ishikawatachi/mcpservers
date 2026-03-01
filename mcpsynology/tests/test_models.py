"""
Tests for Pydantic input models.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from synology_mcp.models import ListFilesInput, ShareInput, PackageInput


# ---------------------------------------------------------------------------
# ListFilesInput
# ---------------------------------------------------------------------------

class TestListFilesInput:
    def test_valid_root_share(self) -> None:
        inp = ListFilesInput(folder_path="/docker")
        assert inp.folder_path == "/docker"

    def test_valid_nested_path(self) -> None:
        inp = ListFilesInput(folder_path="/homes/admin/documents")
        assert inp.folder_path == "/homes/admin/documents"

    def test_valid_with_additional(self) -> None:
        inp = ListFilesInput(folder_path="/docker", additional="size,owner,time")
        assert inp.additional == "size,owner,time"

    def test_path_traversal_rejected(self) -> None:
        with pytest.raises(ValidationError, match="traversal"):
            ListFilesInput(folder_path="/docker/../etc/passwd")

    def test_empty_path_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListFilesInput(folder_path="")

    def test_path_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ListFilesInput(folder_path="/" + "a" * 513)

    def test_illegal_characters_rejected(self) -> None:
        with pytest.raises(ValidationError, match="illegal"):
            ListFilesInput(folder_path="/docker; rm -rf /")


# ---------------------------------------------------------------------------
# ShareInput
# ---------------------------------------------------------------------------

class TestShareInput:
    def test_valid_simple_name(self) -> None:
        inp = ShareInput(share_name="docker")
        assert inp.share_name == "docker"

    def test_valid_name_with_space(self) -> None:
        inp = ShareInput(share_name="my share")
        assert inp.share_name == "my share"

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ShareInput(share_name="")

    def test_name_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ShareInput(share_name="a" * 65)

    def test_injection_rejected(self) -> None:
        with pytest.raises(ValidationError, match="illegal"):
            ShareInput(share_name="'; DROP TABLE shares; --")


# ---------------------------------------------------------------------------
# PackageInput
# ---------------------------------------------------------------------------

class TestPackageInput:
    def test_valid_package_id(self) -> None:
        inp = PackageInput(package_id="ContainerManager")
        assert inp.package_id == "ContainerManager"

    def test_valid_with_hyphen(self) -> None:
        inp = PackageInput(package_id="Hyper-Backup")
        assert inp.package_id == "Hyper-Backup"

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PackageInput(package_id="")

    def test_injection_rejected(self) -> None:
        with pytest.raises(ValidationError, match="illegal"):
            PackageInput(package_id="pkg; rm -rf /")
