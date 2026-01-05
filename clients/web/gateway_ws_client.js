/* Minimal gateway v1 WebSocket client (ciphertext only). */
(() => {
  const connection_status = document.getElementById('connection_status');
  const debug_log = document.getElementById('debug_log');
  const event_log = document.getElementById('event_log');

  const gateway_url_input = document.getElementById('gateway_url');
  const bootstrap_token_input = document.getElementById('bootstrap_token');
  const resume_token_input = document.getElementById('resume_token');
  const conv_id_input = document.getElementById('conv_id');
  const from_seq_input = document.getElementById('from_seq');
  const ack_seq_input = document.getElementById('ack_seq');
  const msg_id_input = document.getElementById('msg_id');
  const ciphertext_input = document.getElementById('ciphertext_input');

  const connect_start_btn = document.getElementById('connect_start');
  const connect_resume_btn = document.getElementById('connect_resume');
  const subscribe_btn = document.getElementById('subscribe_btn');
  const replay_btn = document.getElementById('replay_btn');
  const ack_btn = document.getElementById('ack_btn');
  const send_btn = document.getElementById('send_btn');
  const clear_log_btn = document.getElementById('clear_log');

  const append_log = (line) => {
    const now = new Date().toISOString();
    debug_log.value += `[${now}] ${line}\n`;
    debug_log.scrollTop = debug_log.scrollHeight;
  };

  const render_event = (message) => {
    const entry = document.createElement('div');
    const parts = [];
    if (message.conv_id) {
      parts.push(`conv_id=${message.conv_id}`);
    }
    if (typeof message.seq !== 'undefined') {
      parts.push(`seq=${message.seq}`);
    }
    if (message.msg_id) {
      parts.push(`msg_id=${message.msg_id}`);
    }
    if (message.conv_home) {
      parts.push(`conv_home=${message.conv_home}`);
    }
    if (message.origin_gateway) {
      parts.push(`origin_gateway=${message.origin_gateway}`);
    }
    const body_display = typeof message.body !== 'undefined' ? JSON.stringify(message.body) : '';
    entry.textContent = `${parts.join(' ')} body=${body_display}`;
    event_log.prepend(entry);
  };

  class GatewayWsClient {
    constructor() {
      this.ws = null;
      this.pending_envelopes = [];
    }

    connect(url) {
      if (this.ws) {
        this.ws.close();
      }
      this.pending_envelopes = [];
      append_log(`connecting to ${url}`);
      this.ws = new WebSocket(url);
      this.ws.addEventListener('open', () => {
        connection_status.textContent = 'connected';
        append_log('websocket open');
        this.flush_pending();
      });
      this.ws.addEventListener('close', (evt) => {
        connection_status.textContent = 'disconnected';
        append_log(`websocket closed (code=${evt.code})`);
      });
      this.ws.addEventListener('error', (evt) => {
        append_log(`websocket error: ${evt.message || 'unknown'}`);
      });
      this.ws.addEventListener('message', (evt) => {
        let message;
        try {
          message = JSON.parse(evt.data);
        } catch (err) {
          append_log(`invalid json: ${evt.data}`);
          return;
        }
        this.handle_message(message);
      });
    }

    ensure_connected() {
      return this.ws && this.ws.readyState === WebSocket.OPEN;
    }

    send_envelope(type, body) {
      const envelope = Object.assign({ v: 1, t: type }, body || {});
      if (this.ensure_connected()) {
        this.ws.send(JSON.stringify(envelope));
        append_log(`sent ${type}`);
        return;
      }
      if (this.ws && this.ws.readyState === WebSocket.CONNECTING) {
        this.pending_envelopes.push(envelope);
        append_log(`queued ${type} until open`);
        return;
      }
      append_log('websocket not connected');
    }

    flush_pending() {
      if (!this.ensure_connected()) {
        return;
      }
      while (this.pending_envelopes.length > 0) {
        const envelope = this.pending_envelopes.shift();
        this.ws.send(JSON.stringify(envelope));
        append_log(`sent queued ${envelope.t}`);
      }
    }

    start_session(token) {
      if (!token) {
        append_log('missing bootstrap token');
        return;
      }
      this.send_envelope('session.start', { token });
    }

    resume_session(resume_token) {
      if (!resume_token) {
        append_log('missing resume_token');
        return;
      }
      this.send_envelope('session.resume', { resume_token });
    }

    subscribe(conv_id) {
      if (!conv_id) {
        append_log('missing conv_id');
        return;
      }
      this.send_envelope('conv.subscribe', { conv_id });
    }

    replay(conv_id, from_seq) {
      if (!conv_id) {
        append_log('missing conv_id');
        return;
      }
      const body = { conv_id };
      if (typeof from_seq === 'number' && !Number.isNaN(from_seq)) {
        body.from_seq = from_seq;
      }
      this.send_envelope('conv.replay', body);
    }

    ack(conv_id, ack_seq) {
      if (!conv_id) {
        append_log('missing conv_id');
        return;
      }
      if (typeof ack_seq !== 'number' || Number.isNaN(ack_seq)) {
        append_log('missing ack_seq');
        return;
      }
      this.send_envelope('conv.ack', { conv_id, ack_seq });
    }

    send_ciphertext(conv_id, msg_id, ciphertext) {
      if (!conv_id) {
        append_log('missing conv_id');
        return;
      }
      if (!msg_id) {
        append_log('missing msg_id');
        return;
      }
      if (!ciphertext) {
        append_log('missing ciphertext');
        return;
      }
      this.send_envelope('conv.send', { conv_id, msg_id, body: ciphertext });
    }

    handle_message(message) {
      if (!message || typeof message !== 'object') {
        append_log('ignored non-object message');
        return;
      }
      if (message.t === 'ping') {
        const pong_id = typeof message.id !== 'undefined' ? message.id : `pong-${Date.now()}`;
        this.send_envelope('pong', { id: pong_id });
        append_log('responded to ping');
        return;
      }
      if (message.t === 'conv.event') {
        render_event(message);
        return;
      }
      if (message.t === 'session.resume' && message.resume_token) {
        resume_token_input.value = message.resume_token;
      }
      append_log(`received ${message.t || 'unknown'}: ${JSON.stringify(message)}`);
    }
  }

  const client = new GatewayWsClient();

  connect_start_btn.addEventListener('click', () => {
    const url = gateway_url_input.value.trim();
    if (!url) {
      append_log('gateway url required');
      return;
    }
    client.connect(url);
    const token = bootstrap_token_input.value.trim();
    client.start_session(token);
  });

  connect_resume_btn.addEventListener('click', () => {
    const url = gateway_url_input.value.trim();
    if (!url) {
      append_log('gateway url required');
      return;
    }
    client.connect(url);
    const resume_token = resume_token_input.value.trim();
    client.resume_session(resume_token);
  });

  subscribe_btn.addEventListener('click', () => {
    client.subscribe(conv_id_input.value.trim());
  });

  replay_btn.addEventListener('click', () => {
    const from_seq = Number(from_seq_input.value);
    client.replay(conv_id_input.value.trim(), from_seq);
  });

  ack_btn.addEventListener('click', () => {
    const ack_seq = Number(ack_seq_input.value);
    client.ack(conv_id_input.value.trim(), ack_seq);
  });

  send_btn.addEventListener('click', () => {
    client.send_ciphertext(
      conv_id_input.value.trim(),
      msg_id_input.value.trim(),
      ciphertext_input.value.trim()
    );
  });

  clear_log_btn.addEventListener('click', () => {
    debug_log.value = '';
    event_log.innerHTML = '';
  });
})();
