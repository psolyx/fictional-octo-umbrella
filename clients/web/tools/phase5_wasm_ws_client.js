"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const read_stdin_json = async () => {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf-8").trim();
  if (!raw) {
    throw new Error("stdin payload is required");
  }
  return JSON.parse(raw);
};

const ensure_crypto = () => {
  if (!globalThis.crypto) {
    globalThis.crypto = crypto.webcrypto;
  }
};

const delay_ms = (duration_ms) =>
  new Promise((resolve) => {
    setTimeout(resolve, duration_ms);
  });

const wait_for_condition = async (predicate, timeout_ms, label) => {
  const deadline = Date.now() + timeout_ms;
  while (Date.now() < deadline) {
    if (predicate()) {
      return;
    }
    await delay_ms(10);
  }
  throw new Error(`timeout waiting for ${label}`);
};

const load_wasm = async (wasm_exec_path, wasm_path) => {
  ensure_crypto();
  require(wasm_exec_path);
  if (typeof globalThis.Go !== "function") {
    throw new Error("Go runtime not available after wasm_exec load");
  }
  const go = new globalThis.Go();
  const wasm_bytes = fs.readFileSync(wasm_path);
  const result = await WebAssembly.instantiate(wasm_bytes, go.importObject);
  go.run(result.instance);
  await wait_for_condition(
    () => typeof globalThis.dmCreateParticipant === "function",
    1000,
    "wasm exports"
  );
};

const env_pack = (kind, payload_b64) => {
  if (!Number.isInteger(kind) || kind < 0 || kind > 255) {
    throw new Error("env kind must be 0-255");
  }
  const payload_bytes = Buffer.from(payload_b64, "base64");
  const env_bytes = Buffer.concat([Buffer.from([kind]), payload_bytes]);
  return env_bytes.toString("base64");
};

const env_unpack = (env_b64) => {
  const env_bytes = Buffer.from(env_b64, "base64");
  if (!env_bytes.length) {
    throw new Error("env must contain at least one byte");
  }
  const kind = env_bytes[0];
  const payload_b64 = env_bytes.subarray(1).toString("base64");
  return { kind, payload_b64 };
};

const msg_id_for_env = (env_b64) => {
  const env_bytes = Buffer.from(env_b64, "base64");
  return crypto.createHash("sha256").update(env_bytes).digest("hex");
};

const assert_ok = (result, label) => {
  if (!result || typeof result !== "object" || !result.ok) {
    const error_message = result && result.error ? String(result.error) : "unknown error";
    throw new Error(`${label} failed: ${error_message}`);
  }
  return result;
};

const wasm_call = (name, args, label) => {
  const fn = globalThis[name];
  if (typeof fn !== "function") {
    throw new Error(`missing wasm export ${name}`);
  }
  return assert_ok(fn(...args), label);
};

const open_ws = async (ws_url, timeout_ms) =>
  new Promise((resolve, reject) => {
    if (typeof WebSocket !== "function") {
      reject(new Error("WebSocket is not available in this Node runtime"));
      return;
    }
    const ws = new WebSocket(ws_url);
    const timer = setTimeout(() => {
      reject(new Error("timeout waiting for WebSocket open"));
    }, timeout_ms);
    ws.addEventListener("open", () => {
      clearTimeout(timer);
      resolve(ws);
    });
    ws.addEventListener("error", () => {
      clearTimeout(timer);
      reject(new Error("WebSocket error during connect"));
    });
  });

const create_ws_context = (ws) => {
  const queue = [];
  const waiters = [];
  let closed = false;
  let close_error = null;

  const push_payload = (payload) => {
    if (waiters.length) {
      const waiter = waiters.shift();
      waiter.resolve(payload);
      return;
    }
    queue.push(payload);
  };

  const reject_waiters = (error) => {
    while (waiters.length) {
      const waiter = waiters.shift();
      waiter.reject(error);
    }
  };

  ws.addEventListener("message", (event) => {
    const raw = typeof event.data === "string" ? event.data : Buffer.from(event.data).toString("utf-8");
    let payload;
    try {
      payload = JSON.parse(raw);
    } catch (error) {
      return;
    }
    if (!payload || typeof payload !== "object") {
      return;
    }
    if (payload.t === "ping") {
      ws.send(JSON.stringify({ v: 1, t: "pong", id: payload.id }));
      return;
    }
    push_payload(payload);
  });

  ws.addEventListener("close", () => {
    closed = true;
    reject_waiters(new Error("WebSocket closed"));
  });

  ws.addEventListener("error", () => {
    close_error = new Error("WebSocket error");
    reject_waiters(close_error);
  });

  const next_payload = (timeout_ms) => {
    if (queue.length) {
      return Promise.resolve(queue.shift());
    }
    if (close_error) {
      return Promise.reject(close_error);
    }
    if (closed) {
      return Promise.reject(new Error("WebSocket closed"));
    }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error("timeout waiting for WebSocket payload"));
      }, timeout_ms);
      waiters.push({
        resolve: (payload) => {
          clearTimeout(timer);
          resolve(payload);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });
    });
  };

  const send_json = (payload) => {
    ws.send(JSON.stringify(payload));
  };

  return { next_payload, send_json, ws };
};

const read_payload = async (context, timeout_ms, seen_msg_ids) => {
  const payload = await context.next_payload(timeout_ms);
  if (payload.t !== "conv.event") {
    return payload;
  }
  const body = payload.body;
  if (!body || typeof body !== "object") {
    return payload;
  }
  const conv_id = body.conv_id;
  const msg_id = body.msg_id;
  if (!conv_id || !msg_id) {
    return payload;
  }
  if (!seen_msg_ids[conv_id]) {
    seen_msg_ids[conv_id] = new Set();
  }
  if (seen_msg_ids[conv_id].has(msg_id)) {
    throw new Error(`duplicate conv.event for msg_id ${msg_id}`);
  }
  seen_msg_ids[conv_id].add(msg_id);
  return payload;
};

const wait_for = async (context, predicate, timeout_ms, seen_msg_ids) => {
  const deadline = Date.now() + timeout_ms;
  while (Date.now() < deadline) {
    const remaining = deadline - Date.now();
    const payload = await read_payload(context, remaining, seen_msg_ids);
    if (predicate(payload)) {
      return payload;
    }
  }
  throw new Error("timeout waiting for payload");
};

const wait_for_ack = async (context, request_id, timeout_ms, seen_msg_ids) => {
  const payload = await wait_for(
    context,
    (message) => message.t === "conv.acked" && message.id === request_id,
    timeout_ms,
    seen_msg_ids
  );
  const body = payload.body;
  if (!body || typeof body !== "object" || typeof body.seq !== "number") {
    throw new Error("invalid conv.acked payload");
  }
  return body.seq;
};

const wait_for_event = async (context, conv_id, seq, timeout_ms, seen_msg_ids) => {
  const payload = await wait_for(
    context,
    (message) =>
      message.t === "conv.event" &&
      message.body &&
      message.body.conv_id === conv_id &&
      message.body.seq === seq,
    timeout_ms,
    seen_msg_ids
  );
  const body = payload.body;
  if (!body || typeof body !== "object") {
    throw new Error("invalid conv.event payload");
  }
  const computed_msg_id = msg_id_for_env(body.env);
  if (computed_msg_id !== body.msg_id) {
    throw new Error("msg_id does not match env bytes");
  }
  return payload;
};

const wait_for_no_duplicate = async (context, conv_id, msg_id, timeout_ms, seen_msg_ids) => {
  const deadline = Date.now() + timeout_ms;
  while (Date.now() < deadline) {
    const remaining = deadline - Date.now();
    let payload;
    try {
      payload = await read_payload(context, remaining, seen_msg_ids);
    } catch (error) {
      if (String(error.message).includes("timeout")) {
        return;
      }
      throw error;
    }
    if (payload.t !== "conv.event") {
      continue;
    }
    const body = payload.body;
    if (!body || typeof body !== "object") {
      continue;
    }
    if (body.conv_id === conv_id && body.msg_id === msg_id) {
      throw new Error("duplicate conv.event observed after resend");
    }
  }
};

const send_env = async (context, conv_id, env_b64, request_id, timeout_ms, seen_msg_ids) => {
  const msg_id = msg_id_for_env(env_b64);
  context.send_json({
    v: 1,
    t: "conv.send",
    id: request_id,
    body: { conv_id, msg_id, env: env_b64 },
  });
  const seq = await wait_for_ack(context, request_id, timeout_ms, seen_msg_ids);
  return { seq, msg_id };
};

const main = async () => {
  const input = await read_stdin_json();
  const repo_root = path.resolve(__dirname, "..", "..", "..");
  const wasm_exec_path = path.join(repo_root, "clients", "web", "vendor", "wasm_exec.js");
  const wasm_path = path.join(repo_root, "clients", "web", "vendor", "mls_harness.wasm");

  await load_wasm(wasm_exec_path, wasm_path);

  const ws = await open_ws(input.ws_url, 1000);
  const context = create_ws_context(ws);
  const seen_msg_ids = {};

  context.send_json({
    v: 1,
    t: "session.start",
    id: "session_start",
    body: { auth_token: input.auth_token, device_id: input.device_id },
  });
  await wait_for(
    context,
    (payload) => payload.t === "session.ready",
    1000,
    seen_msg_ids
  );

  context.send_json({
    v: 1,
    t: "conv.subscribe",
    id: "sub_dm",
    body: { conv_id: input.dm.conv_id, from_seq: 1 },
  });
  context.send_json({
    v: 1,
    t: "conv.subscribe",
    id: "sub_room",
    body: { conv_id: input.room.conv_id, from_seq: 1 },
  });

  let dm_participant_b64 = wasm_call(
    "dmCreateParticipant",
    [input.dm.participant_name, input.dm.participant_seed],
    "dm_create_participant"
  ).participant_b64;
  const dm_init = wasm_call(
    "dmInit",
    [dm_participant_b64, input.dm.bob_keypackage_b64, input.dm.group_id_b64, input.dm.init_seed],
    "dm_init"
  );
  dm_participant_b64 = dm_init.participant_b64;
  const dm_welcome_env = env_pack(1, dm_init.welcome_b64);
  const dm_commit_env = env_pack(2, dm_init.commit_b64);

  let room_participant_b64 = wasm_call(
    "dmCreateParticipant",
    [input.room.participant_name, input.room.participant_seed],
    "room_create_participant"
  ).participant_b64;
  const room_init = wasm_call(
    "groupInit",
    [
      room_participant_b64,
      [input.room.bob_keypackage_b64, input.room.guest_keypackage_b64],
      input.room.group_id_b64,
      input.room.init_seed,
    ],
    "group_init"
  );
  room_participant_b64 = room_init.participant_b64;
  const room_welcome_env = env_pack(1, room_init.welcome_b64);
  const room_commit_env = env_pack(2, room_init.commit_b64);

  let dm_expected_seq = 1;
  let room_expected_seq = 1;

  const dm_welcome = await send_env(context, input.dm.conv_id, dm_welcome_env, "dm_welcome", 1000, seen_msg_ids);
  if (dm_welcome.seq !== dm_expected_seq) {
    throw new Error("dm welcome seq mismatch");
  }
  await wait_for_event(context, input.dm.conv_id, dm_expected_seq, 1000, seen_msg_ids);
  dm_expected_seq += 1;

  const dm_commit = await send_env(context, input.dm.conv_id, dm_commit_env, "dm_commit", 1000, seen_msg_ids);
  if (dm_commit.seq !== dm_expected_seq) {
    throw new Error("dm commit seq mismatch");
  }
  await wait_for_event(context, input.dm.conv_id, dm_expected_seq, 1000, seen_msg_ids);
  dm_participant_b64 = wasm_call(
    "dmCommitApply",
    [dm_participant_b64, dm_init.commit_b64],
    "dm_commit_apply"
  ).participant_b64;
  dm_expected_seq += 1;

  const room_welcome = await send_env(
    context,
    input.room.conv_id,
    room_welcome_env,
    "room_welcome",
    1000,
    seen_msg_ids
  );
  if (room_welcome.seq !== room_expected_seq) {
    throw new Error("room welcome seq mismatch");
  }
  await wait_for_event(context, input.room.conv_id, room_expected_seq, 1000, seen_msg_ids);
  room_expected_seq += 1;

  const room_commit = await send_env(
    context,
    input.room.conv_id,
    room_commit_env,
    "room_commit",
    1000,
    seen_msg_ids
  );
  if (room_commit.seq !== room_expected_seq) {
    throw new Error("room commit seq mismatch");
  }
  await wait_for_event(context, input.room.conv_id, room_expected_seq, 1000, seen_msg_ids);
  room_participant_b64 = wasm_call(
    "dmCommitApply",
    [room_participant_b64, room_init.commit_b64],
    "room_commit_apply"
  ).participant_b64;
  room_expected_seq += 1;

  const dm_ciphertext = wasm_call(
    "dmEncrypt",
    [dm_participant_b64, input.dm.app_plaintext],
    "dm_encrypt"
  );
  dm_participant_b64 = dm_ciphertext.participant_b64;
  const dm_app_env = env_pack(3, dm_ciphertext.ciphertext_b64);
  const dm_app = await send_env(context, input.dm.conv_id, dm_app_env, "dm_app", 1000, seen_msg_ids);
  if (dm_app.seq !== dm_expected_seq) {
    throw new Error("dm app seq mismatch");
  }
  await wait_for_event(context, input.dm.conv_id, dm_expected_seq, 1000, seen_msg_ids);
  dm_expected_seq += 1;

  const room_ciphertext = wasm_call(
    "dmEncrypt",
    [room_participant_b64, input.room.app_plaintext],
    "room_encrypt"
  );
  room_participant_b64 = room_ciphertext.participant_b64;
  const room_app_env = env_pack(3, room_ciphertext.ciphertext_b64);
  const room_app = await send_env(context, input.room.conv_id, room_app_env, "room_app", 1000, seen_msg_ids);
  if (room_app.seq !== room_expected_seq) {
    throw new Error("room app seq mismatch");
  }
  await wait_for_event(context, input.room.conv_id, room_expected_seq, 1000, seen_msg_ids);
  room_expected_seq += 1;

  const dm_reply_event = await wait_for_event(
    context,
    input.dm.conv_id,
    dm_expected_seq,
    2000,
    seen_msg_ids
  );
  const dm_reply_payload = env_unpack(dm_reply_event.body.env);
  if (dm_reply_payload.kind !== 3) {
    throw new Error("dm reply kind mismatch");
  }
  const dm_reply_text = wasm_call(
    "dmDecrypt",
    [dm_participant_b64, dm_reply_payload.payload_b64],
    "dm_decrypt"
  ).plaintext;
  if (dm_reply_text !== input.dm.reply_plaintext) {
    throw new Error("dm reply plaintext mismatch");
  }
  dm_expected_seq += 1;

  const room_reply_event = await wait_for_event(
    context,
    input.room.conv_id,
    room_expected_seq,
    2000,
    seen_msg_ids
  );
  const room_reply_payload = env_unpack(room_reply_event.body.env);
  if (room_reply_payload.kind !== 3) {
    throw new Error("room reply kind mismatch");
  }
  const room_reply_text = wasm_call(
    "dmDecrypt",
    [room_participant_b64, room_reply_payload.payload_b64],
    "room_decrypt"
  ).plaintext;
  if (room_reply_text !== input.room.reply_plaintext) {
    throw new Error("room reply plaintext mismatch");
  }
  room_expected_seq += 1;

  context.send_json({
    v: 1,
    t: "conv.send",
    id: "dm_app_resend",
    body: {
      conv_id: input.dm.conv_id,
      msg_id: dm_app.msg_id,
      env: dm_app_env,
    },
  });
  const resend_seq = await wait_for_ack(context, "dm_app_resend", 1000, seen_msg_ids);
  if (resend_seq !== dm_app.seq) {
    throw new Error("resend did not preserve seq");
  }
  await wait_for_no_duplicate(context, input.dm.conv_id, dm_app.msg_id, 300, seen_msg_ids);

  ws.close();
};

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`${message}\n`);
  process.exit(1);
});
