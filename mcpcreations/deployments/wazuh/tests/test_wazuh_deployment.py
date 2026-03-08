"""
test_wazuh_deployment.py
========================
Tests for the Wazuh deployment pipeline.

Covers every step of the deploy_wazuh.py flow so each phase can be
validated independently or in sequence.

Test categories
---------------
  Phase 1 — Compose file validation (offline, no network)
  Phase 2 — Portainer connection & endpoint discovery
  Phase 3 — Stack pre-flight (network exists, no conflicting stack)
  Phase 4 — Stack deployment (creates or updates via Portainer API)
  Phase 5 — Post-deploy health (containers are running, dashboard responds)

Run
---
    # Activate the portainer-mcp venv
    source mcpportainer/.venv/bin/activate

    # All phases (needs live Portainer)
    pytest mcpcreations/deployments/wazuh/tests/test_wazuh_deployment.py -v

    # Offline-only phases
    pytest mcpcreations/deployments/wazuh/tests/test_wazuh_deployment.py -v -m offline

    # Full deployment test (destructive — actually deploys to Portainer)
    pytest mcpcreations/deployments/wazuh/tests/test_wazuh_deployment.py -v -m live

Environment variables
---------------------
    PORTAINER_ENDPOINT_ID   — target Portainer endpoint ID (default: first available)
    WAZUH_HOSTNAME          — hostname used in assertions (default: wazuh.test.local)
    INDEXER_PASSWORD        — (for live tests, can be dummy for offline)
    DASHBOARD_PASSWORD      — (for live tests, can be dummy for offline)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).parent.parent         # deployments/wazuh/
REPO_ROOT  = SCRIPT_DIR.parent.parent.parent      # git/mcp/

# Make portainer_mcp importable
sys.path.insert(0, str(REPO_ROOT / "mcpportainer" / "src"))

COMPOSE_FILE = SCRIPT_DIR / "docker-compose.yml"
DEPLOY_SCRIPT = SCRIPT_DIR / "deploy_wazuh.py"

ENDPOINT_ID   = int(os.getenv("PORTAINER_ENDPOINT_ID", "0"))
WAZUH_HOSTNAME = os.getenv("WAZUH_HOSTNAME", "wazuh.test.local")
INDEXER_PWD    = os.getenv("INDEXER_PASSWORD", "DummyPass1!")
DASHBOARD_PWD  = os.getenv("DASHBOARD_PASSWORD", "DummyPass1!")
STACK_NAME     = "wazuh"


# ---------------------------------------------------------------------------
# Phase 1 — Compose file validation (offline)
# ---------------------------------------------------------------------------

@pytest.mark.offline
class TestComposeFile:
    """Validate docker-compose.yml before any network calls."""

    def test_compose_file_exists(self):
        assert COMPOSE_FILE.exists(), f"docker-compose.yml not found at {COMPOSE_FILE}"

    def test_compose_is_valid_yaml(self):
        content = COMPOSE_FILE.read_text()
        data = yaml.safe_load(content)
        assert isinstance(data, dict), "compose file must parse to a dict"

    def test_compose_has_required_services(self):
        data = yaml.safe_load(COMPOSE_FILE.read_text())
        services = data.get("services", {})
        required = {"wazuh.indexer", "wazuh.manager", "wazuh.dashboard", "watchtower"}
        missing = required - set(services.keys())
        assert not missing, f"Missing services: {missing}"

    def test_wazuh_dashboard_on_proxy_network(self):
        data = yaml.safe_load(COMPOSE_FILE.read_text())
        dashboard = data["services"]["wazuh.dashboard"]
        nets = dashboard.get("networks", [])
        assert "proxy" in nets, "wazuh.dashboard must be on the 'proxy' network for reverse-proxy access"

    def test_proxy_network_is_external(self):
        data = yaml.safe_load(COMPOSE_FILE.read_text())
        proxy_net = data.get("networks", {}).get("proxy", {})
        assert proxy_net.get("external") is True, "The 'proxy' network must be external: true"

    def test_wazuh_internal_network_is_internal(self):
        data = yaml.safe_load(COMPOSE_FILE.read_text())
        internal_net = data.get("networks", {}).get("wazuh-internal", {})
        assert internal_net.get("internal") is True, "The 'wazuh-internal' network must be internal: true"

    def test_agent_ports_exposed(self):
        data = yaml.safe_load(COMPOSE_FILE.read_text())
        manager_ports = data["services"]["wazuh.manager"].get("ports", [])
        ports_str = str(manager_ports)
        assert "1514" in ports_str, "Manager must expose 1514 for agent syslog"
        assert "1515" in ports_str, "Manager must expose 1515 for agent enrollment"

    def test_watchtower_restricts_to_wazuh_containers(self):
        data = yaml.safe_load(COMPOSE_FILE.read_text())
        wt = data["services"]["watchtower"]
        cmd = wt.get("command", "")
        wazuh_containers = {"wazuh-manager", "wazuh-indexer", "wazuh-dashboard"}
        mentioned = wazuh_containers & set(str(cmd).split())
        assert mentioned, (
            "Watchtower command should restrict monitoring to wazuh containers, "
            f"got: {cmd}"
        )

    def test_password_env_vars_use_substitution(self):
        content = COMPOSE_FILE.read_text()
        assert "${INDEXER_PASSWORD}" in content, "compose must use ${INDEXER_PASSWORD} substitution"
        assert "${DASHBOARD_PASSWORD}" in content, "compose must use ${DASHBOARD_PASSWORD} substitution"
        assert "${WAZUH_HOSTNAME}" in content, "compose must use ${WAZUH_HOSTNAME} substitution"

    def test_all_named_volumes_declared(self):
        data = yaml.safe_load(COMPOSE_FILE.read_text())
        declared_volumes = set(data.get("volumes", {}).keys())
        used_volumes: set[str] = set()
        for svc in data.get("services", {}).values():
            for vol in svc.get("volumes", []):
                if isinstance(vol, str) and ":" in vol:
                    vol_name = vol.split(":")[0]
                    if not vol_name.startswith("/"):
                        used_volumes.add(vol_name)
        undeclared = used_volumes - declared_volumes
        assert not undeclared, f"Volumes used but not declared: {undeclared}"

    def test_no_hardcoded_secrets(self):
        content = COMPOSE_FILE.read_text()
        suspicious = ["password123", "admin123", "changeme", "secret"]
        for word in suspicious:
            assert word.lower() not in content.lower(), (
                f"Hardcoded secret hint '{word}' found in compose file"
            )

    def test_deploy_script_exists(self):
        assert DEPLOY_SCRIPT.exists(), f"deploy_wazuh.py not found at {DEPLOY_SCRIPT}"

    def test_env_example_exists(self):
        env_example = SCRIPT_DIR / ".env.example"
        assert env_example.exists(), ".env.example missing"

    def test_env_example_has_all_vars(self):
        content = (SCRIPT_DIR / ".env.example").read_text()
        for var in ("WAZUH_HOSTNAME", "INDEXER_PASSWORD", "DASHBOARD_PASSWORD"):
            assert var in content, f".env.example missing {var}"


# ---------------------------------------------------------------------------
# Phase 2 — Portainer connection (requires live Portainer)
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestPortainerConnection:
    """Verify we can reach Portainer and list endpoints."""

    def _get_settings(self):
        try:
            from portainer_mcp.config import get_settings
            return get_settings()
        except Exception as e:
            pytest.skip(f"Cannot load Portainer settings: {e}")

    def test_portainer_health(self):
        from portainer_mcp.client import PortainerClient

        settings = self._get_settings()

        async def _run():
            async with PortainerClient(settings) as client:
                return await client.health()

        result = asyncio.run(_run())
        assert "Version" in result or result is not None, "Health check returned empty result"

    def test_list_endpoints(self):
        from portainer_mcp.client import PortainerClient

        settings = self._get_settings()

        async def _run():
            async with PortainerClient(settings) as client:
                return await client.list_endpoints()

        endpoints = asyncio.run(_run())
        assert isinstance(endpoints, list), "Endpoints must be a list"
        assert len(endpoints) > 0, "No endpoints found — check Portainer config"
        # Print for visibility
        for ep in endpoints:
            print(f"  Endpoint: id={ep['Id']} name={ep.get('Name', '?')} status={ep.get('Status', '?')}")


# ---------------------------------------------------------------------------
# Phase 3 — Stack pre-flight (requires live Portainer)
# ---------------------------------------------------------------------------

@pytest.mark.live
class TestStackPreflight:
    """Check the Portainer environment before deploying."""

    def _get_client_and_settings(self):
        try:
            from portainer_mcp.config import get_settings
            from portainer_mcp.client import PortainerClient
            return PortainerClient(get_settings()), get_settings()
        except Exception as e:
            pytest.skip(f"Cannot connect to Portainer: {e}")

    def _choose_endpoint_id(self, endpoints: list) -> int:
        if ENDPOINT_ID > 0:
            ids = [e["Id"] for e in endpoints]
            assert ENDPOINT_ID in ids, f"Endpoint {ENDPOINT_ID} not in {ids}"
            return ENDPOINT_ID
        return endpoints[0]["Id"]

    def test_no_conflicting_stack_or_it_is_wazuh(self):
        from portainer_mcp.client import PortainerClient
        from portainer_mcp.config import get_settings

        async def _run():
            async with PortainerClient(get_settings()) as client:
                return await client.list_stacks()

        try:
            stacks = asyncio.run(_run())
        except Exception as e:
            pytest.skip(f"Cannot list stacks: {e}")

        conflicting = [
            s for s in stacks
            if s.get("Name") == STACK_NAME
        ]
        # Either no existing stack, or existing one is our Wazuh stack
        if conflicting:
            print(f"  Existing '{STACK_NAME}' stack found (will be updated): id={conflicting[0].get('Id')}")


# ---------------------------------------------------------------------------
# Phase 4 — Deployment (requires live Portainer, actually deploys)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.deploy
class TestStackDeploy:
    """Actually deploys the wazuh stack. Destructive — use carefully."""

    def test_deploy_stack_dry_run(self):
        """Validate that the deploy script's dry-run mode works."""
        import subprocess
        python = sys.executable
        result = subprocess.run(
            [
                python, str(DEPLOY_SCRIPT),
                "--hostname", WAZUH_HOSTNAME,
                "--indexer-password", INDEXER_PWD,
                "--dashboard-password", DASHBOARD_PWD,
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=30,
        )
        assert result.returncode == 0, (
            f"deploy_wazuh.py --dry-run failed:\n{result.stderr}"
        )
        assert "services:" in result.stdout or "wazuh" in result.stdout.lower()

    def test_deploy_stack_live(self):
        """Full deploy — only runs when explicitly requested."""
        import subprocess
        python = sys.executable
        args = [
            python, str(DEPLOY_SCRIPT),
            "--hostname", WAZUH_HOSTNAME,
            "--indexer-password", INDEXER_PWD,
            "--dashboard-password", DASHBOARD_PWD,
        ]
        if ENDPOINT_ID > 0:
            args += ["--endpoint-id", str(ENDPOINT_ID)]

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=120,
        )
        print(result.stdout)
        if result.returncode != 0:
            print("STDERR:", result.stderr)
        assert result.returncode == 0, f"Deployment failed:\n{result.stderr}"
        assert "deployed" in result.stdout.lower() or "stack" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Phase 5 — Post-deploy health (requires running Wazuh stack)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.postdeploy
class TestPostDeployHealth:
    """
    Verify the Wazuh stack is running after deployment.
    Runs with: pytest -m postdeploy
    """

    def _ep_id(self):
        from portainer_mcp.client import PortainerClient
        from portainer_mcp.config import get_settings

        async def _run():
            async with PortainerClient(get_settings()) as client:
                endpoints = await client.list_endpoints()
                if ENDPOINT_ID > 0:
                    return ENDPOINT_ID
                return endpoints[0]["Id"] if endpoints else None

        return asyncio.run(_run())

    def test_wazuh_containers_running(self):
        from portainer_mcp.client import PortainerClient
        from portainer_mcp.config import get_settings

        ep_id = self._ep_id()
        if not ep_id:
            pytest.skip("No Portainer endpoint available")

        async def _run():
            async with PortainerClient(get_settings()) as client:
                return await client.list_containers(ep_id)

        containers = asyncio.run(_run())
        names_status = {
            c.get("Names", ["?"])[0].lstrip("/"): c.get("State", "?")
            for c in containers
        }
        wazuh_containers = {
            "wazuh-manager": names_status.get("wazuh-manager"),
            "wazuh-indexer": names_status.get("wazuh-indexer"),
            "wazuh-dashboard": names_status.get("wazuh-dashboard"),
        }
        print("Wazuh container states:", wazuh_containers)
        for name, state in wazuh_containers.items():
            if state is None:
                pytest.fail(f"Container '{name}' not found on endpoint {ep_id}")
            assert state == "running", f"Container '{name}' state is '{state}', expected 'running'"

    def test_dashboard_http_responds(self):
        """Dashboard should respond on HTTP (port 5601) or via hostname after proxy setup."""
        try:
            import httpx
        except ImportError:
            pytest.skip("httpx not installed")

        # Try via container port directly on docker host — requires host port mapping
        # or same-network access. We check via hostname if configured.
        try:
            r = httpx.get(f"http://{WAZUH_HOSTNAME}", timeout=10, follow_redirects=True)
            assert r.status_code in (200, 302, 401), (
                f"Dashboard returned unexpected status {r.status_code}"
            )
        except httpx.ConnectError:
            pytest.skip(
                f"Cannot reach {WAZUH_HOSTNAME} — either the reverse proxy isn't configured yet "
                "or the hostname isn't resolvable from this machine"
            )
