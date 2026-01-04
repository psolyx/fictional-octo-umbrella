import argparse
import asyncio
import json
import time

import aiohttp


async def open_ws_session(session: aiohttp.ClientSession, device_id: str, resume_token: str):
    ws = await session.ws_connect("/v1/ws")
    await ws.send_json(
        {"v": 1, "t": "session.resume", "id": f"resume-{device_id}", "body": {"resume_token": resume_token}}
    )
    ready = await ws.receive_json()
    if ready.get("t") != "session.ready":
        raise RuntimeError(f"unexpected response during resume: {ready}")
    return ws


async def start_device(
    session: aiohttp.ClientSession, conv_id: str, auth_token: str, device_id: str, subscribe: bool = True
):
    start_resp = await session.post(
        "/v1/session/start", json={"auth_token": auth_token, "device_id": device_id}
    )
    start_resp.raise_for_status()
    ready = await start_resp.json()
    session_token = ready["session_token"]
    resume_token = ready["resume_token"]

    ws = await open_ws_session(session, device_id, resume_token)
    if subscribe:
        await ws.send_json({"v": 1, "t": "conv.subscribe", "id": f"sub-{device_id}", "body": {"conv_id": conv_id, "from_seq": 1}})
    return ws, session_token


async def create_room(session: aiohttp.ClientSession, conv_id: str, session_token: str):
    resp = await session.post(
        "/v1/rooms/create", json={"conv_id": conv_id, "members": []}, headers={"Authorization": f"Bearer {session_token}"}
    )
    resp.raise_for_status()
    await resp.json()


async def reader(ws: aiohttp.ClientWebSocketResponse, stats: dict):
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data.get("t") == "conv.event":
                stats["events"] += 1
                msg_id = data["body"].get("msg_id")
                if msg_id in stats["seen_ids"]:
                    stats["dups"] += 1
                else:
                    stats["seen_ids"].add(msg_id)
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            break


async def send_messages(ws: aiohttp.ClientWebSocketResponse, conv_id: str, count: int, device_idx: int):
    for i in range(count):
        msg_id = f"load-{device_idx}-{i}"
        await ws.send_json(
            {
                "v": 1,
                "t": "conv.send",
                "id": msg_id,
                "body": {"conv_id": conv_id, "msg_id": msg_id, "env": "ZW4=", "ts": int(time.time() * 1000)},
            }
        )


async def main():
    parser = argparse.ArgumentParser(description="Gateway load tester")
    parser.add_argument("--base-url", default="http://localhost:8080", help="Gateway base URL")
    parser.add_argument("--conv-id", default="load-room", help="Conversation id to reuse")
    parser.add_argument("--auth-token", default="load-user", help="Auth token for all devices")
    parser.add_argument("--sessions", type=int, default=5, help="Number of websocket sessions")
    parser.add_argument("--messages", type=int, default=0, help="Messages to send per session")
    parser.add_argument("--drain-seconds", type=float, default=2.0, help="Time to wait for events")
    args = parser.parse_args()

    timeout = aiohttp.ClientTimeout(total=None)
    async with aiohttp.ClientSession(base_url=args.base_url, timeout=timeout) as session:
        first_resp = await session.post(
            "/v1/session/start", json={"auth_token": args.auth_token, "device_id": "device-0"}
        )
        first_resp.raise_for_status()
        first_ready = await first_resp.json()
        first_token = first_ready["session_token"]
        first_resume = first_ready["resume_token"]

        await create_room(session, args.conv_id, first_token)
        sockets = []
        stats = []

        first_ws = await open_ws_session(session, "device-0", first_resume)
        await first_ws.send_json({"v": 1, "t": "conv.subscribe", "id": "sub-0", "body": {"conv_id": args.conv_id, "from_seq": 1}})
        sockets.append(first_ws)
        stats.append({"events": 0, "dups": 0, "seen_ids": set()})

        for i in range(1, args.sessions):
            ws, _ = await start_device(session, args.conv_id, args.auth_token, f"device-{i}")
            sockets.append(ws)
            stats.append({"events": 0, "dups": 0, "seen_ids": set()})

        readers = [asyncio.create_task(reader(ws, stat)) for ws, stat in zip(sockets, stats)]

        senders = []
        if args.messages > 0:
            for idx, ws in enumerate(sockets):
                senders.append(asyncio.create_task(send_messages(ws, args.conv_id, args.messages, idx)))

        if senders:
            await asyncio.gather(*senders)

        await asyncio.sleep(args.drain_seconds)

        for ws in sockets:
            await ws.close()
        for task in readers:
            task.cancel()
        await asyncio.gather(*readers, return_exceptions=True)

    total_events = sum(stat["events"] for stat in stats)
    total_dups = sum(stat["dups"] for stat in stats)
    print("Connections:", len(sockets))
    print("Events received:", total_events)
    print("Duplicate msg_ids detected:", total_dups)


if __name__ == "__main__":
    asyncio.run(main())
