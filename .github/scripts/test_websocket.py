#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os

import websockets


async def main() -> None:
    url = os.environ.get("WEBSOCKET_URL", "ws://127.0.0.1:18080/")
    async with websockets.connect(url, open_timeout=10, close_timeout=5) as websocket:
        waiter = await websocket.ping()
        await asyncio.wait_for(waiter, timeout=5)
        print(f"WebSocket handshake and ping succeeded: {url}")


if __name__ == "__main__":
    asyncio.run(main())
