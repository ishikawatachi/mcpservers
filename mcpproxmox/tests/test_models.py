"""Tests for Proxmox MCP input models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from proxmox_mcp.models import NodeInput, VmInput, ShutdownVmInput, StorageInput


# ---------------------------------------------------------------------------
# NodeInput
# ---------------------------------------------------------------------------

def test_node_input_valid():
    m = NodeInput(node="pve")
    assert m.node == "pve"


def test_node_input_rejects_shell_injection():
    with pytest.raises(ValidationError):
        NodeInput(node="pve; rm -rf /")


def test_node_input_rejects_too_long():
    with pytest.raises(ValidationError):
        NodeInput(node="a" * 65)


# ---------------------------------------------------------------------------
# VmInput
# ---------------------------------------------------------------------------

def test_vm_input_valid():
    m = VmInput(node="pve", vmid=100)
    assert m.vmid == 100


def test_vm_input_rejects_low_vmid():
    with pytest.raises(ValidationError):
        VmInput(node="pve", vmid=99)


def test_vm_input_rejects_high_vmid():
    with pytest.raises(ValidationError):
        VmInput(node="pve", vmid=10_000_000)


# ---------------------------------------------------------------------------
# ShutdownVmInput
# ---------------------------------------------------------------------------

def test_shutdown_defaults():
    m = ShutdownVmInput(node="pve", vmid=100)
    assert m.timeout == 60


def test_shutdown_custom_timeout():
    m = ShutdownVmInput(node="pve", vmid=100, timeout=120)
    assert m.timeout == 120


def test_shutdown_rejects_timeout_too_high():
    with pytest.raises(ValidationError):
        ShutdownVmInput(node="pve", vmid=100, timeout=601)


# ---------------------------------------------------------------------------
# StorageInput
# ---------------------------------------------------------------------------

def test_storage_input_valid():
    m = StorageInput(node="pve", storage="local-lvm")
    assert m.storage == "local-lvm"


def test_storage_input_rejects_injection():
    with pytest.raises(ValidationError):
        StorageInput(node="pve", storage="local; cat /etc/passwd")
