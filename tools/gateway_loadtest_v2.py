from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp


@dataclass
class SessionStats:
    events: int = 0
    duplicates: int = 0
    reconnects: int = 0
    seen_ids: Dict[str, int] = field(default_factory=dict)
    next_from_seq: Dict[str, int] = field(default_factory=dict)


@dataclass
class SessionState:
    device_id: str
    conv_id: str
    resume_token: str
    session_token: str
    ws: aiohttp.ClientWebSocketResponse
    stats: SessionStats
    reader_task: asyncio.Task
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def create_room(session: aiohttp.ClientSession, conv_id: str, session_token: str) -> None:
    resp = await session.post(
        '/v1/rooms/create', json={'conv_id': conv_id, 'members': []}, headers={'Authorization': f'Bearer {session_token}'}
    )
    resp.raise_for_status()
    await resp.json()


async def start_device(
    session: aiohttp.ClientSession, conv_id: str, auth_token: str, device_id: str, subscribe: bool = True
) -> SessionState:
    start_resp = await session.post(
        '/v1/session/start', json={'auth_token': auth_token, 'device_id': device_id}
    )
    start_resp.raise_for_status()
    ready = await start_resp.json()
    session_token = ready['session_token']
    resume_token = ready['resume_token']

    ws, ready_body = await open_ws_session(session, device_id, resume_token)
    stats = SessionStats()
    if subscribe:
        await send_subscribe(ws, conv_id, stats)
    update_from_ready(stats, ready_body)
    reader_task = asyncio.create_task(reader(ws, stats))
    return SessionState(device_id, conv_id, ready_body['resume_token'], session_token, ws, stats, reader_task)


async def open_ws_session(
    session: aiohttp.ClientSession, device_id: str, resume_token: str
) -> tuple[aiohttp.ClientWebSocketResponse, Dict[str, Any]]:
    ws = await session.ws_connect('/v1/ws')
    await ws.send_json(
        {'v': 1, 't': 'session.resume', 'id': f'resume-{device_id}', 'body': {'resume_token': resume_token}}
    )
    ready = await ws.receive_json()
    if ready.get('t') != 'session.ready':
        raise RuntimeError(f'unexpected response during resume: {ready}')
    body = ready.get('body') or {}
    if 'resume_token' not in body:
        raise RuntimeError(f'ready frame missing resume_token: {ready}')
    return ws, body


async def send_subscribe(ws: aiohttp.ClientWebSocketResponse, conv_id: str, stats: SessionStats) -> None:
    from_seq = stats.next_from_seq.get(conv_id) or 1
    await ws.send_json(
        {
            'v': 1,
            't': 'conv.subscribe',
            'id': f'sub-{conv_id}-{int(time.time() * 1000)}',
            'body': {'conv_id': conv_id, 'from_seq': from_seq},
        }
    )


def update_from_ready(stats: SessionStats, ready_body: Dict[str, Any]) -> None:
    for cursor in ready_body.get('cursors', []):
        conv_id = cursor.get('conv_id')
        next_seq = cursor.get('next_seq')
        if conv_id and isinstance(next_seq, int):
            stats.next_from_seq[conv_id] = next_seq


async def reader(ws: aiohttp.ClientWebSocketResponse, stats: SessionStats) -> None:
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            if data.get('t') == 'conv.event':
                body = data.get('body') or {}
                conv_id = body.get('conv_id')
                seq = body.get('seq')
                msg_id = body.get('msg_id')
                if conv_id and isinstance(seq, int):
                    stats.next_from_seq[conv_id] = seq + 1
                if msg_id is not None:
                    if msg_id in stats.seen_ids:
                        stats.duplicates += 1
                    else:
                        stats.seen_ids[msg_id] = seq if isinstance(seq, int) else -1
                stats.events += 1
        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            break


async def send_messages(state: SessionState, count: int, interval_s: float) -> None:
    for i in range(count):
        msg_id = f'load-{state.device_id}-{i}'
        payload = {
            'v': 1,
            't': 'conv.send',
            'id': msg_id,
            'body': {'conv_id': state.conv_id, 'msg_id': msg_id, 'env': 'ZW4=', 'ts': int(time.time() * 1000)},
        }
        async with state.lock:
            await state.ws.send_json(payload)
        if interval_s > 0:
            await asyncio.sleep(interval_s)


async def perform_resume(http_session: aiohttp.ClientSession, state: SessionState) -> None:
    async with state.lock:
        await state.ws.close()
    await asyncio.gather(state.reader_task, return_exceptions=True)

    ws, ready_body = await open_ws_session(http_session, state.device_id, state.resume_token)
    update_from_ready(state.stats, ready_body)
    async with state.lock:
        state.ws = ws
    await send_subscribe(ws, state.conv_id, state.stats)
    state.reader_task = asyncio.create_task(reader(ws, state.stats))
    state.resume_token = ready_body['resume_token']
    state.stats.reconnects += 1


class ProcMetricsCollector:
    def __init__(self, pid: int):
        self.pid = pid
        self.samples: List[tuple[float, Optional[int], Optional[float]]] = []
        self._stop = asyncio.Event()
        self._ticks_per_second = os.sysconf(os.sysconf_names['SC_CLK_TCK'])

    def _read_rss_bytes(self) -> Optional[int]:
        try:
            with open(f'/proc/{self.pid}/status', 'r', encoding='utf-8') as handle:
                for line in handle:
                    if line.startswith('VmRSS:'):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            return int(parts[1]) * 1024
            return None
        except FileNotFoundError:
            return None

    def _read_cpu_ticks(self) -> Optional[int]:
        try:
            with open(f'/proc/{self.pid}/stat', 'r', encoding='utf-8') as handle:
                fields = handle.read().split()
            if len(fields) >= 17:
                utime = int(fields[13])
                stime = int(fields[14])
                return utime + stime
            return None
        except FileNotFoundError:
            return None

    async def run(self, interval_s: float = 1.0) -> None:
        prev_ticks = self._read_cpu_ticks()
        prev_time = time.time()
        while not self._stop.is_set():
            await asyncio.sleep(interval_s)
            now = time.time()
            ticks = self._read_cpu_ticks()
            rss = self._read_rss_bytes()
            if ticks is None or prev_ticks is None:
                cpu_pct = None
            else:
                elapsed_ticks = ticks - prev_ticks
                cpu_pct = (elapsed_ticks / self._ticks_per_second) / max(now - prev_time, 1e-6) * 100.0
            self.samples.append((now, rss, cpu_pct))
            prev_ticks = ticks
            prev_time = now

    def stop(self) -> None:
        self._stop.set()

    def max_rss(self) -> Optional[int]:
        rss_values = [sample[1] for sample in self.samples if sample[1] is not None]
        return max(rss_values) if rss_values else None

    def cpu_average_and_peak(self) -> tuple[Optional[float], Optional[float]]:
        cpu_values = [sample[2] for sample in self.samples if sample[2] is not None]
        if not cpu_values:
            return None, None
        return sum(cpu_values) / len(cpu_values), max(cpu_values)


def spawn_server(base_url: str) -> subprocess.Popen[bytes]:
    parsed = urlparse(base_url)
    host = parsed.hostname or '127.0.0.1'
    port = parsed.port or 8080
    python_path = os.path.join('gateway', '.venv', 'bin', 'python')
    if not os.path.exists(python_path):
        sys.exit("gateway/.venv missing. Run 'ALLOW_AIOHTTP_STUB=0 make -C gateway setup' first.")

    cmd = [python_path, '-m', 'gateway.server', 'serve', '--host', host, '--port', str(port)]
    return subprocess.Popen(cmd, cwd='gateway')


async def wait_for_ready(session: aiohttp.ClientSession, attempts: int = 10) -> None:
    for _ in range(attempts):
        try:
            async with session.get('/healthz') as resp:
                if resp.status < 500:
                    await resp.text()
                    return
        except Exception:
            await asyncio.sleep(0.5)
            continue
        await asyncio.sleep(0.2)
    await asyncio.sleep(1.0)


def format_bytes(num_bytes: Optional[int]) -> str:
    if num_bytes is None:
        return 'n/a'
    for unit in ['B', 'KiB', 'MiB', 'GiB']:
        if num_bytes < 1024 or unit == 'GiB':
            return f'{num_bytes:.1f} {unit}'
        num_bytes /= 1024
    return f'{num_bytes:.1f} GiB'


async def main() -> None:
    parser = argparse.ArgumentParser(description='Gateway load tester v2')
    parser.add_argument('--base-url', default='http://127.0.0.1:8080', help='Gateway base URL')
    parser.add_argument('--conv-id', default='load-room', help='Conversation id to reuse')
    parser.add_argument('--auth-token', default='load-user', help='Auth token for all devices')
    parser.add_argument('--sessions', type=int, default=5, help='Number of websocket sessions')
    parser.add_argument('--messages', type=int, default=0, help='Messages to send per session')
    parser.add_argument('--message-interval', type=float, default=0.0, help='Delay between messages per session (seconds)')
    parser.add_argument('--duration-seconds', type=float, default=60.0, help='How long to keep sessions open')
    parser.add_argument('--drain-seconds', type=float, default=5.0, help='Time to wait for events before closing')
    parser.add_argument('--resume-cycles', type=int, default=0, help='Resume storms per session')
    parser.add_argument('--spawn-server', action='store_true', help='Spawn a local gateway server from gateway/.venv')
    parser.add_argument('--json-out', type=str, default=None, help='Write metrics to a JSON file')
    args = parser.parse_args()

    metrics_collector: Optional[ProcMetricsCollector] = None
    metrics_task: Optional[asyncio.Task] = None
    server_process: Optional[subprocess.Popen[bytes]] = None
    sessions: List[SessionState] = []

    timeout = aiohttp.ClientTimeout(total=None)
    try:
        async with aiohttp.ClientSession(base_url=args.base_url, timeout=timeout) as session:
            if args.spawn_server:
                server_process = spawn_server(args.base_url)
                metrics_collector = ProcMetricsCollector(server_process.pid)
                metrics_task = asyncio.create_task(metrics_collector.run())
                await wait_for_ready(session)

            first_resp = await session.post(
                '/v1/session/start', json={'auth_token': args.auth_token, 'device_id': 'device-0'}
            )
            first_resp.raise_for_status()
            first_ready = await first_resp.json()
            first_token = first_ready['session_token']
            first_resume = first_ready['resume_token']

            await create_room(session, args.conv_id, first_token)

            first_ws, first_ready_body = await open_ws_session(session, 'device-0', first_resume)
            first_stats = SessionStats()
            await send_subscribe(first_ws, args.conv_id, first_stats)
            update_from_ready(first_stats, first_ready_body)
            first_reader = asyncio.create_task(reader(first_ws, first_stats))
            sessions = [
                SessionState(
                    'device-0', args.conv_id, first_ready_body['resume_token'], first_token, first_ws, first_stats, first_reader
                )
            ]

            for i in range(1, args.sessions):
                state = await start_device(session, args.conv_id, args.auth_token, f'device-{i}')
                sessions.append(state)

        senders = []
        if args.messages > 0:
            for state in sessions:
                senders.append(asyncio.create_task(send_messages(state, args.messages, args.message_interval)))

            resume_tasks = []
            if args.resume_cycles > 0:
                interval = max(args.duration_seconds / max(args.resume_cycles, 1), 0.1)
                for state in sessions:
                    resume_tasks.append(
                        asyncio.create_task(
                            perform_resumes(session, state, args.resume_cycles, interval)
                        )
                    )

            await asyncio.gather(*senders)
            await asyncio.sleep(args.duration_seconds)
            await asyncio.gather(*resume_tasks)
            await asyncio.sleep(args.drain_seconds)

            for state in sessions:
                async with state.lock:
                    await state.ws.close()
                await asyncio.gather(state.reader_task, return_exceptions=True)
    finally:
        if metrics_collector and metrics_task:
            metrics_collector.stop()
            await metrics_task

        if server_process:
            server_process.terminate()
            try:
                server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server_process.kill()

    summary = {
        'connections': 0,
        'sessions': len(sessions),
        'reconnects': sum(state.stats.reconnects for state in sessions),
        'events': sum(state.stats.events for state in sessions),
        'duplicates': sum(state.stats.duplicates for state in sessions),
        'max_rss_bytes': metrics_collector.max_rss() if metrics_collector else None,
        'cpu_avg_pct': None,
        'cpu_peak_pct': None,
    }
    summary['connections'] = summary['sessions'] + summary['reconnects']
    if metrics_collector:
        cpu_avg, cpu_peak = metrics_collector.cpu_average_and_peak()
        summary['cpu_avg_pct'] = cpu_avg
        summary['cpu_peak_pct'] = cpu_peak

    print('Connections:', summary['connections'])
    print('Reconnects:', summary['reconnects'])
    print('Events received:', summary['events'])
    print('Duplicate msg_ids detected:', summary['duplicates'])
    print('Max RSS:', format_bytes(summary['max_rss_bytes']))
    if summary['cpu_avg_pct'] is not None:
        print(f"CPU avg/peak: {summary['cpu_avg_pct']:.2f}% / {summary['cpu_peak_pct']:.2f}%")

    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as handle:
            json.dump(summary, handle, indent=2)


async def perform_resumes(
    http_session: aiohttp.ClientSession, state: SessionState, cycles: int, interval: float
) -> None:
    for _ in range(cycles):
        await asyncio.sleep(interval)
        try:
            await perform_resume(http_session, state)
        except Exception as exc:
            print(f'[warn] resume failed for {state.device_id}: {exc}')
            break


if __name__ == '__main__':
    asyncio.run(main())
