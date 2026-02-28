"""Tests for Pydantic input model validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from portainer_mcp.models import (
    ContainerInput,
    ContainerLogsInput,
    DeployStackInput,
    EndpointIdInput,
)


class TestEndpointIdInput:
    def test_valid(self):
        m = EndpointIdInput(endpoint_id=1)
        assert m.endpoint_id == 1

    def test_rejects_zero(self):
        with pytest.raises(ValidationError):
            EndpointIdInput(endpoint_id=0)

    def test_rejects_negative(self):
        with pytest.raises(ValidationError):
            EndpointIdInput(endpoint_id=-1)


class TestContainerInput:
    def test_valid(self):
        m = ContainerInput(endpoint_id=1, container_id="abc123")
        assert m.container_id == "abc123"

    def test_rejects_shell_metacharacters(self):
        for bad in ["abc;ls", "cmd|grep", "$(evil)", "`cmd`"]:
            with pytest.raises(ValidationError, match="illegal characters"):
                ContainerInput(endpoint_id=1, container_id=bad)

    def test_rejects_empty_id(self):
        with pytest.raises(ValidationError):
            ContainerInput(endpoint_id=1, container_id="")

    def test_rejects_too_long_id(self):
        with pytest.raises(ValidationError):
            ContainerInput(endpoint_id=1, container_id="x" * 129)


class TestContainerLogsInput:
    def test_defaults(self):
        m = ContainerLogsInput(endpoint_id=1, container_id="abc")
        assert m.tail == 100
        assert m.timestamps is False

    def test_custom_tail(self):
        m = ContainerLogsInput(endpoint_id=1, container_id="abc", tail=500)
        assert m.tail == 500

    def test_rejects_tail_over_limit(self):
        with pytest.raises(ValidationError):
            ContainerLogsInput(endpoint_id=1, container_id="abc", tail=9999)

    def test_rejects_tail_zero(self):
        with pytest.raises(ValidationError):
            ContainerLogsInput(endpoint_id=1, container_id="abc", tail=0)


class TestDeployStackInput:
    def test_valid(self):
        m = DeployStackInput(
            endpoint_id=1,
            stack_name="my-stack",
            compose_content="version: '3'\nservices:\n  web:\n    image: nginx",
        )
        assert m.stack_name == "my-stack"

    def test_rejects_invalid_stack_name(self):
        with pytest.raises(ValidationError, match="alphanumerics"):
            DeployStackInput(
                endpoint_id=1,
                stack_name="bad name!",
                compose_content="version: '3'",
            )

    def test_rejects_empty_compose(self):
        with pytest.raises(ValidationError):
            DeployStackInput(endpoint_id=1, stack_name="ok", compose_content="")

    def test_env_vars_optional(self):
        m = DeployStackInput(
            endpoint_id=1,
            stack_name="test",
            compose_content="version: '3'",
        )
        assert m.env_vars == {}

    def test_env_vars_provided(self):
        m = DeployStackInput(
            endpoint_id=1,
            stack_name="test",
            compose_content="version: '3'",
            env_vars={"KEY": "value"},
        )
        assert m.env_vars["KEY"] == "value"
