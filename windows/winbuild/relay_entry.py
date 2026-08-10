"""PyInstaller entry: roofspan-relay-connector.exe — outbound-only Secure Relay tunnel.

Loads the installation identity (created by the existing licensing flow) and opens an authenticated
OUTBOUND WebSocket to the RoofSpan relay, forwarding routed Mobile requests to the LOCAL backend. No
inbound ports. Native execution HUMAN REQUIRED.
"""
import asyncio
import os

from licensing.identity import get_or_create_identity
from relay.tunnel_client import InstallationTunnel


def main() -> None:
    os.environ.setdefault("INSTALLATION_KEYS_DIR", r"C:\ProgramData\RoofSpan\identity")
    private_key, installation_id = get_or_create_identity()
    relay_ws_url = os.environ["ROOFSPAN_RELAY_WS_URL"]  # e.g. wss://relay.roofspan.io/api/relay/tunnel
    local_api_url = os.environ.get("ROOFSPAN_LOCAL_API_URL", "http://127.0.0.1:8001")
    tunnel = InstallationTunnel(relay_ws_url, installation_id, private_key, local_api_url)
    asyncio.run(tunnel.run())


if __name__ == "__main__":
    main()
