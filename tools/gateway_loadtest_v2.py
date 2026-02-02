from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
import tempfile
from typing import IO, Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp


@dataclass
class SessionStats:
    events: int = 0
    duplicates: int = 0
    msg_id_conflicts: int = 0
    seq_duplicates: int = 0
    out_of_order: int = 0
    reconnects: int = 0
    seen_ids: Dict[str, int] = field(default_factory=dict)
    next_from_seq: Dict[str, int] = field(default_factory=dict)
    seqs_seen: Dict[str, set[int]] = field(default_factory=dict)
    last_seq_by_conv: Dict[str, int] = field(default_factory=dict)


@dataclass
class SessionState:
    device_id: str
    conv_id: str
    resume_token: str
    session_token: str
    ws: aiohttp.ClientWebSocketResponse
    stats: SessionStats
    reader_task: asyncio.Task
    online: bool = True
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def create_room(
    session: aiohttp.ClientSession, conv_id: str, session_token: str, members: Optional[List[str]] = None
) -> None:
    if members is None:
        members = []
    resp = await session.post(
        '/v1/rooms/create',
        json={'conv_id': conv_id, 'members': members},
        headers={'Authorization': f'Bearer {session_token}'},
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
                    seqs_seen = stats.seqs_seen.setdefault(conv_id, set())
                    if seq in seqs_seen:
                        stats.seq_duplicates += 1
                    else:
                        seqs_seen.add(seq)
                    last_seq = stats.last_seq_by_conv.get(conv_id)
                    if last_seq is not None and seq <= last_seq:
                        stats.out_of_order += 1
                    if last_seq is None or seq > last_seq:
                        stats.last_seq_by_conv[conv_id] = seq
                if msg_id is not None:
                    if msg_id in stats.seen_ids:
                        stats.duplicates += 1
                        prev_seq = stats.seen_ids.get(msg_id)
                        if isinstance(seq, int) and prev_seq not in (None, -1) and prev_seq != seq:
                            stats.msg_id_conflicts += 1
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
    await disconnect_state(state)
    await reconnect_state(http_session, state)


async def disconnect_state(state: SessionState) -> None:
    if not state.online:
        return
    async with state.lock:
        await state.ws.close()
    await asyncio.gather(state.reader_task, return_exceptions=True)
    state.online = False


async def reconnect_state(http_session: aiohttp.ClientSession, state: SessionState) -> None:
    if state.online:
        return
    ws, ready_body = await open_ws_session(http_session, state.device_id, state.resume_token)
    update_from_ready(state.stats, ready_body)
    async with state.lock:
        state.ws = ws
    await send_subscribe(ws, state.conv_id, state.stats)
    state.reader_task = asyncio.create_task(reader(ws, state.stats))
    state.resume_token = ready_body['resume_token']
    state.stats.reconnects += 1
    state.online = True


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


def pick_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def spawn_server(host: str, port: int) -> tuple[subprocess.Popen[bytes], IO[str], Path]:
    repo_root = Path(__file__).resolve().parent.parent
    gateway_root = repo_root / 'gateway'
    python_path = gateway_root / '.venv' / 'bin' / 'python'
    if not python_path.exists():
        sys.exit("gateway/.venv missing. Run 'ALLOW_AIOHTTP_STUB=0 make -C gateway setup' first.")

    env = os.environ.copy()
    env.setdefault('PYTHONPATH', str(gateway_root / 'src'))

    log_file = tempfile.NamedTemporaryFile(mode='w+', encoding='utf-8', delete=False)
    cmd = [str(python_path), '-m', 'gateway.server', 'serve', '--host', host, '--port', str(port)]
    process = subprocess.Popen(cmd, cwd=gateway_root, env=env, stdout=log_file, stderr=subprocess.STDOUT)
    return process, log_file, Path(log_file.name)


def _read_log_excerpt(log_file: IO[str], max_bytes: int = 4000) -> str:
    log_file.flush()
    log_file.seek(0, os.SEEK_END)
    end = log_file.tell()
    if end == 0:
        return ''
    to_read = min(max_bytes, end)
    log_file.seek(-to_read, os.SEEK_END)
    return log_file.read()


async def wait_for_ready(
    session: aiohttp.ClientSession,
    attempts: int = 10,
    *,
    process: Optional[subprocess.Popen[bytes]] = None,
    log_file: Optional[IO[str]] = None,
) -> None:
    for _ in range(attempts):
        if process and process.poll() is not None:
            details = _read_log_excerpt(log_file) if log_file else ''
            message = f'Gateway server exited early with code {process.returncode}.'
            if details:
                message += f"\nServer output:\n{details}"
            raise RuntimeError(message)
        try:
            async with session.get('/healthz') as resp:
                body = await resp.text()
                if resp.status == 200 and body.strip() == 'ok':
                    return
        except Exception:
            await asyncio.sleep(0.5)
            continue
        await asyncio.sleep(0.2)
    details = _read_log_excerpt(log_file) if log_file else ''
    message = 'Gateway did not become ready after health checks.'
    if details:
        message += f"\nServer output:\n{details}"
    raise RuntimeError(message)


def format_bytes(num_bytes: Optional[int]) -> str:
    if num_bytes is None:
        return 'n/a'
    for unit in ['B', 'KiB', 'MiB', 'GiB']:
        if num_bytes < 1024 or unit == 'GiB':
            return f'{num_bytes:.1f} {unit}'
        num_bytes /= 1024
    return f'{num_bytes:.1f} GiB'


async def run_basic(session: aiohttp.ClientSession, args: argparse.Namespace) -> tuple[Dict[str, Any], List[SessionState]]:
    sessions: List[SessionState] = []
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
            'device-0',
            args.conv_id,
            first_ready_body['resume_token'],
            first_token,
            first_ws,
            first_stats,
            first_reader,
        )
    ]

    for i in range(1, args.sessions):
        state = await start_device(session, args.conv_id, args.auth_token, f'device-{i}')
        sessions.append(state)

    senders: list[asyncio.Task] = []
    if args.messages > 0:
        for state in sessions:
            senders.append(asyncio.create_task(send_messages(state, args.messages, args.message_interval)))

    resume_tasks: list[asyncio.Task] = []
    if args.resume_cycles > 0:
        interval = max(args.duration_seconds / max(args.resume_cycles, 1), 0.1)
        for state in sessions:
            resume_tasks.append(asyncio.create_task(perform_resumes(session, state, args.resume_cycles, interval)))

    if senders:
        await asyncio.gather(*senders)

    await asyncio.sleep(args.duration_seconds)

    if resume_tasks:
        await asyncio.gather(*resume_tasks)

    await asyncio.sleep(args.drain_seconds)

    close_tasks = []
    for state in sessions:
        await disconnect_state(state)
        close_tasks.append(state.reader_task)
    if close_tasks:
        await asyncio.gather(*close_tasks, return_exceptions=True)

    summary = {
        'connections': sum(1 for _ in sessions),
        'sessions': len(sessions),
        'reconnects': sum(state.stats.reconnects for state in sessions),
        'events': sum(state.stats.events for state in sessions),
        'duplicates': sum(state.stats.duplicates for state in sessions),
        'cpu_avg_pct': None,
        'cpu_peak_pct': None,
    }
    summary['connections'] = summary['sessions'] + summary['reconnects']
    return summary, sessions


async def run_room_fanout(
    session: aiohttp.ClientSession, args: argparse.Namespace
) -> tuple[Dict[str, Any], List[SessionState]]:
    if args.members < 1:
        raise RuntimeError('members must be >= 1')
    if args.msg_per_sec <= 0:
        raise RuntimeError('msg_per_sec must be > 0')
    if args.duration_s <= 0:
        raise RuntimeError('duration_s must be > 0')
    if not (0.0 <= args.offline_frac <= 1.0):
        raise RuntimeError('offline_frac must be between 0 and 1')
    if args.retry_frac < 0.0 or args.retry_frac > 1.0:
        raise RuntimeError('retry_frac must be between 0 and 1')

    user_ids = [f'load-user-{i}' for i in range(args.members)]
    first_resp = await session.post(
        '/v1/session/start', json={'auth_token': user_ids[0], 'device_id': 'device-0'}
    )
    first_resp.raise_for_status()
    first_ready = await first_resp.json()
    first_token = first_ready['session_token']
    first_resume = first_ready['resume_token']

    await create_room(session, args.conv_id, first_token, user_ids)

    sessions: List[SessionState] = []
    first_ws, first_ready_body = await open_ws_session(session, 'device-0', first_resume)
    first_stats = SessionStats()
    await send_subscribe(first_ws, args.conv_id, first_stats)
    update_from_ready(first_stats, first_ready_body)
    first_reader = asyncio.create_task(reader(first_ws, first_stats))
    sessions.append(
        SessionState(
            'device-0',
            args.conv_id,
            first_ready_body['resume_token'],
            first_token,
            first_ws,
            first_stats,
            first_reader,
        )
    )

    for i in range(1, args.members):
        state = await start_device(session, args.conv_id, user_ids[i], f'device-{i}')
        sessions.append(state)

    stop_churn = asyncio.Event()
    churn_task: Optional[asyncio.Task] = None
    if args.offline_frac > 0 and args.churn_interval_s > 0:
        churn_task = asyncio.create_task(run_churn(session, sessions, args, stop_churn))

    send_summary = await run_send_loop(sessions, args)
    stop_churn.set()
    if churn_task:
        await churn_task

    await reconnect_all(session, sessions)
    await asyncio.sleep(args.drain_seconds)
    await close_all(sessions)

    summary = build_fanout_summary(sessions, args, send_summary)
    return summary, sessions


async def close_all(sessions: List[SessionState]) -> None:
    close_tasks = []
    for state in sessions:
        await disconnect_state(state)
        close_tasks.append(state.reader_task)
    if close_tasks:
        await asyncio.gather(*close_tasks, return_exceptions=True)


async def reconnect_all(session: aiohttp.ClientSession, sessions: List[SessionState]) -> None:
    tasks = [reconnect_state(session, state) for state in sessions if not state.online]
    if tasks:
        await asyncio.gather(*tasks)


async def run_churn(
    session: aiohttp.ClientSession, sessions: List[SessionState], args: argparse.Namespace, stop_event: asyncio.Event
) -> None:
    offline: set[str] = set()
    sender_ids = select_sender_ids(sessions, args.sender_mode)
    while not stop_event.is_set():
        await asyncio.sleep(args.churn_interval_s)
        if stop_event.is_set():
            break
        if offline:
            for state in sessions:
                if state.device_id in offline:
                    await reconnect_state(session, state)
            offline.clear()
        candidates = [
            state for state in sessions if state.device_id not in sender_ids and state.online
        ]
        target_offline = max(0, int(len(sessions) * args.offline_frac))
        if candidates and target_offline > 0:
            for state in random.sample(candidates, min(len(candidates), target_offline)):
                await disconnect_state(state)
                offline.add(state.device_id)


def select_sender_ids(sessions: List[SessionState], sender_mode: str) -> set[str]:
    if sender_mode == 'owner':
        return {sessions[0].device_id}
    return set()


async def run_send_loop(sessions: List[SessionState], args: argparse.Namespace) -> Dict[str, Any]:
    interval = 1.0 / args.msg_per_sec
    end_time = time.monotonic() + args.duration_s
    next_send = time.monotonic()
    sent = 0
    retries = 0
    rr_index = 0
    while time.monotonic() < end_time:
        now = time.monotonic()
        if now < next_send:
            await asyncio.sleep(next_send - now)
        sender = pick_sender(sessions, args.sender_mode, rr_index)
        if sender is None:
            await asyncio.sleep(interval)
            next_send = time.monotonic() + interval
            continue
        msg_id = f'load-{sender.device_id}-{sent}'
        await send_message(sender, args.conv_id, msg_id)
        sent += 1
        if args.sender_mode == 'round_robin':
            rr_index += 1
        if args.retry_frac > 0 and random.random() < args.retry_frac:
            await send_message(sender, args.conv_id, msg_id)
            retries += 1
        next_send += interval
    return {'sent': sent, 'retries': retries}


def pick_sender(sessions: List[SessionState], sender_mode: str, rr_index: int) -> Optional[SessionState]:
    online = [state for state in sessions if state.online]
    if not online:
        return None
    if sender_mode == 'owner':
        return sessions[0] if sessions[0].online else online[0]
    if sender_mode == 'random':
        return random.choice(online)
    if sender_mode == 'round_robin':
        return online[rr_index % len(online)]
    return online[0]


async def send_message(state: SessionState, conv_id: str, msg_id: str) -> None:
    payload = {
        'v': 1,
        't': 'conv.send',
        'id': msg_id,
        'body': {'conv_id': conv_id, 'msg_id': msg_id, 'env': 'ZW4=', 'ts': int(time.time() * 1000)},
    }
    async with state.lock:
        await state.ws.send_json(payload)


def build_fanout_summary(
    sessions: List[SessionState], args: argparse.Namespace, send_summary: Dict[str, Any]
) -> Dict[str, Any]:
    max_seq = 0
    total_received = 0
    seq_duplicates = 0
    out_of_order = 0
    msg_id_duplicates = 0
    msg_id_conflicts = 0
    gap_devices: List[str] = []
    max_seq_by_device: Dict[str, int] = {}
    for state in sessions:
        stats = state.stats
        total_received += stats.events
        seq_duplicates += stats.seq_duplicates
        out_of_order += stats.out_of_order
        msg_id_duplicates += stats.duplicates
        msg_id_conflicts += stats.msg_id_conflicts
        seqs = stats.seqs_seen.get(args.conv_id, set())
        if seqs:
            device_max = max(seqs)
            max_seq_by_device[state.device_id] = device_max
            max_seq = max(max_seq, device_max)
        else:
            max_seq_by_device[state.device_id] = 0

    for state in sessions:
        seqs = state.stats.seqs_seen.get(args.conv_id, set())
        if not seqs:
            gap_devices.append(state.device_id)
            continue
        min_seq = min(seqs)
        max_seq_state = max_seq_by_device.get(state.device_id, 0)
        if min_seq != 1 or len(seqs) != max_seq_state:
            gap_devices.append(state.device_id)
        elif max_seq_state != max_seq:
            gap_devices.append(state.device_id)

    exit_code = 0
    violations = []
    if seq_duplicates > 0:
        violations.append('seq_duplicates')
    if out_of_order > 0:
        violations.append('out_of_order')
    if gap_devices:
        violations.append('gaps')
    if msg_id_conflicts > 0:
        violations.append('msg_id_conflicts')
    if violations:
        exit_code = 1

    summary_lines = [
        f"Sent messages: {send_summary['sent']}",
        f"Retry sends: {send_summary['retries']}",
        f"Events received: {total_received}",
        f"Max seq: {max_seq}",
        f"Seq duplicates: {seq_duplicates}",
        f"Seq gaps: {len(gap_devices)}",
        f"Out-of-order: {out_of_order}",
        f"Msg_id duplicates: {msg_id_duplicates}",
        f"Msg_id conflicts: {msg_id_conflicts}",
    ]

    summary = {
        'connections': len(sessions) + sum(state.stats.reconnects for state in sessions),
        'sessions': len(sessions),
        'reconnects': sum(state.stats.reconnects for state in sessions),
        'events': total_received,
        'duplicates': msg_id_duplicates,
        'max_seq': max_seq,
        'gaps': gap_devices,
        'seq_duplicates': seq_duplicates,
        'out_of_order': out_of_order,
        'msg_id_conflicts': msg_id_conflicts,
        'sent': send_summary['sent'],
        'retry_sends': send_summary['retries'],
        'exit_code': exit_code,
        'summary_lines': summary_lines,
        'cpu_avg_pct': None,
        'cpu_peak_pct': None,
    }
    if violations:
        summary['violations'] = violations
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser(description='Gateway load tester v2')
    parser.add_argument('--scenario', default='basic', choices=['basic', 'room-fanout'], help='Scenario to run')
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
    parser.add_argument('--spawn-port', type=int, default=0, help='Port for spawned server (0 = auto-pick)')
    parser.add_argument('--json-out', type=str, default=None, help='Write metrics to a JSON file')
    parser.add_argument('--members', type=int, default=200, help='Room member count (room-fanout)')
    parser.add_argument('--msg_per_sec', type=float, default=100.0, help='Target messages per second (room-fanout)')
    parser.add_argument('--duration_s', type=float, default=60.0, help='Send duration seconds (room-fanout)')
    parser.add_argument(
        '--sender_mode', default='owner', choices=['owner', 'round_robin', 'random'], help='Sender strategy (room-fanout)'
    )
    parser.add_argument('--offline_frac', type=float, default=0.0, help='Fraction of members to churn offline')
    parser.add_argument('--churn_interval_s', type=float, default=0.0, help='Seconds between churn cycles')
    parser.add_argument('--retry_frac', type=float, default=0.0, help='Fraction of sends to retry with same msg_id')
    args = parser.parse_args()

    metrics_collector: Optional[ProcMetricsCollector] = None
    metrics_task: Optional[asyncio.Task] = None
    server_process: Optional[subprocess.Popen[bytes]] = None
    sessions: List[SessionState] = []

    server_log: Optional[IO[str]] = None
    server_log_path: Optional[Path] = None
    base_url = args.base_url
    spawn_host: Optional[str] = None
    spawn_port: Optional[int] = None

    if args.spawn_server:
        parsed = urlparse(args.base_url)
        spawn_host = parsed.hostname or '127.0.0.1'
        spawn_port = args.spawn_port if args.spawn_port is not None else 0
        if spawn_port == 0:
            spawn_port = pick_free_port(spawn_host)
        scheme = parsed.scheme or 'http'
        base_url = f'{scheme}://{spawn_host}:{spawn_port}'

    timeout = aiohttp.ClientTimeout(total=None)
    try:
        async with aiohttp.ClientSession(base_url=base_url, timeout=timeout) as session:
            if args.spawn_server:
                if spawn_host is None or spawn_port is None:
                    raise RuntimeError('spawn_host and spawn_port must be set when spawning server')
                server_process, server_log, server_log_path = spawn_server(spawn_host, spawn_port)
                metrics_collector = ProcMetricsCollector(server_process.pid)
                metrics_task = asyncio.create_task(metrics_collector.run())
                await wait_for_ready(session, process=server_process, log_file=server_log)

            if args.scenario == 'room-fanout':
                summary, sessions = await run_room_fanout(session, args)
            else:
                summary, sessions = await run_basic(session, args)
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

        if server_log:
            server_log.close()
        if server_log_path and server_log_path.exists():
            server_log_path.unlink()

    summary['max_rss_bytes'] = metrics_collector.max_rss() if metrics_collector else None
    if metrics_collector:
        cpu_avg, cpu_peak = metrics_collector.cpu_average_and_peak()
        summary['cpu_avg_pct'] = cpu_avg
        summary['cpu_peak_pct'] = cpu_peak

    if summary.get('summary_lines'):
        for line in summary['summary_lines']:
            print(line)
    else:
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

    if summary.get('exit_code', 0) != 0:
        raise SystemExit(summary['exit_code'])


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
