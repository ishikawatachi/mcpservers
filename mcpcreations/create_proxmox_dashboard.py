import json
import asyncio
from grafana_mcp.client import GrafanaClient

def main():
    with open("proxmox_dashboard.json") as f:
        dashboard = json.load(f)
    body = {
        "dashboard": dashboard,
        "message": "Created by MCP Proxmox dashboard script",
        "overwrite": True
    }
    async def run():
        client = GrafanaClient()
        result = await client.post("dashboards/db", body)
        print(json.dumps(result, indent=2))
    asyncio.run(run())

if __name__ == "__main__":
    main()
