"""Connect the Python SDK to a real QVAC worker and round-trip a heartbeat.

No model is loaded or downloaded. Needs QVAC_WORKER_PATH and QVAC_BARE_PATH.
Prints one JSON line and exits non-zero on failure.
"""
import asyncio
import json
import sys


async def main():
    from tetherto.qvac_sdk.client import Client
    from tetherto.qvac_sdk.methods import heartbeat
    from tetherto.qvac_sdk._generated.models import HeartbeatRequest
    async with Client() as client:
        reply = await heartbeat(client.transport, HeartbeatRequest(type="heartbeat"))
        return reply.type


try:
    kind = asyncio.run(asyncio.wait_for(main(), 60))
    print(json.dumps({"ok": kind == "heartbeat", "reply": kind}))
    sys.exit(0 if kind == "heartbeat" else 1)
except Exception as exc:  # report the exact failure, it is the point of the test
    print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}))
    sys.exit(1)
