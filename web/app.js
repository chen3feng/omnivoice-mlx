const $ = (sel) => document.querySelector(sel);
const t = window.OmniI18n.t;

const chat = $('#chat');
const micBtn = $('#mic');
const statusEl = $('#status');
const speakerSel = $('#speaker');
const modelSel = $('#model');
const langSel = $('#lang');
const textForm = $('#textForm');
const textInput = $('#textInput');
const healthEl = $('#health');
const continuousToggle = $('#continuous');
const nativeToggle = $('#nativeAudio');
const keepTranscriptToggle = $('#keepTranscript');
const hintEl = $('#hint');

let recorder = null;
let chunks = [];
let recording = false;
let busy = false;
let recTimer = null;
let recStart = 0;
let toastTimer = null;
let transcriptDefaultApplied = false;

/* ---------- continuous listening (energy VAD) ---------- */

const cont = {
  active: false,
  paused: false,
  stream: null,
  ctx: null,
  source: null,
  proc: null,
  mute: null,
  noiseFloor: 0.008,
  threshold: 0.012,
  calibFrames: 0,
  calibNeeded: 35, // 35 x 20ms = 700ms
  calibSum: 0,
  state: 'idle',
  voiceRun: 0,
  silenceRun: 0,
  segment: [],
  preRoll: [],
};

function setStatus(state, extra = '') {
  statusEl.dataset.state = state;
  statusEl.textContent = t(`status.${state}`) + extra;
}

function modelName() {
  return modelSel.value === 'minicpm' ? 'MiniCPM-o 4.5' : 'Qwen3-Omni';
}

function defaultHint() {
  if (nativeToggle.checked) {
    return t(modelSel.value === 'minicpm' ? 'hint.native.minicpm' : 'hint.native.qwen');
  }
  if (cont.active) return t('hint.continuous');
  return t('hint.default');
}

function syncModelControls() {
  const mini = modelSel.value === 'minicpm';
  // MiniCPM speaks with a reference voice chosen by language, not the Qwen
  // speaker presets, so the speaker selector does not apply.
  speakerSel.disabled = mini;
  speakerSel.title = mini ? t('title.voiceMini') : '';
  // MiniCPM always needs the Whisper transcript for its reference voice.
  keepTranscriptToggle.disabled = mini;
  hintEl.textContent = defaultHint();
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function toast(message) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('show'), 3200);
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    chat.scrollTop = chat.scrollHeight;
  });
}

function removeEmpty() {
  const empty = document.getElementById('empty');
  if (empty) empty.remove();
}

/* ---------- health ---------- */

async function checkHealth() {
  try {
    const r = await fetch('/api/health');
    const j = await r.json();
    // Match the checkbox to the server default on first load only; afterwards
    // the user's choice wins.
    if (!transcriptDefaultApplied && j.keep_transcript != null) {
      keepTranscriptToggle.checked = !!j.keep_transcript;
      transcriptDefaultApplied = true;
    }
    if (j.ready) {
      const name = j.loaded === 'minicpm' ? 'MiniCPM'
        : j.loaded === 'qwen+minicpm' ? 'Qwen+MiniCPM' : 'Qwen';
      const load = j.loaded === 'minicpm' ? j.minicpm_load_s : j.load_s;
      healthEl.textContent = t('health.ready', {
        name,
        load: Number(load || 0).toFixed(1),
      });
      healthEl.classList.add('ready');
      healthEl.classList.remove('error');
    } else {
      healthEl.textContent = t('health.loading');
      setTimeout(checkHealth, 1500);
    }
  } catch {
    healthEl.textContent = t('health.offline');
    healthEl.classList.add('error');
    healthEl.classList.remove('ready');
    setTimeout(checkHealth, 3000);
  }
}

/* ---------- push-to-talk ---------- */

function pickMime() {
  if (typeof MediaRecorder === 'undefined') return '';
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
  ];
  return candidates.find((t) => MediaRecorder.isTypeSupported(t)) || '';
}

function startTimer() {
  recStart = Date.now();
  recTimer = setInterval(() => {
    const s = Math.floor((Date.now() - recStart) / 1000);
    setStatus('listening', ` ${s}s`);
  }, 250);
}

function stopTimer() {
  if (recTimer) clearInterval(recTimer);
  recTimer = null;
}

async function startRecording() {
  if (busy || cont.active) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    chunks = [];
    const mime = pickMime();
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size) chunks.push(e.data);
    };

    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      const type = recorder.mimeType || mime || 'audio/webm';
      const blob = new Blob(chunks, { type });
      if (blob.size < 800) {
        setStatus('idle');
        return;
      }
      handleAudio(blob, false);
    };

    recorder.start();
    recording = true;
    micBtn.classList.add('recording');
    startTimer();
  } catch (err) {
    toast(t('toast.mic', { err: err.message || err }));
    setStatus('idle');
  }
}

function stopRecording() {
  if (!recording) return;
  recording = false;
  micBtn.classList.remove('recording');
  stopTimer();
  setStatus('transcribing');
  try {
    recorder.stop();
  } catch {
    setStatus('idle');
  }
}

/* ---------- continuous mode ---------- */

async function startContinuous() {
  if (cont.active) return;
  if (busy) {
    toast(t('toast.busy'));
    continuousToggle.checked = false;
    return;
  }
  if (recording) stopRecording();

  let ctx = null;
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    ctx = new AC();
    if (ctx.state === 'suspended') await ctx.resume();

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    const source = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const mute = ctx.createGain();
    mute.gain.value = 0;

    Object.assign(cont, {
      active: true,
      paused: false,
      stream,
      ctx,
      source,
      proc,
      mute,
      noiseFloor: 0.008,
      threshold: 0.012,
      calibFrames: 0,
      calibSum: 0,
      state: 'idle',
      voiceRun: 0,
      silenceRun: 0,
      segment: [],
      preRoll: [],
    });

    proc.onaudioprocess = (e) => {
      const data = e.inputBuffer.getChannelData(0);
      const frameSize = Math.max(1, Math.round(ctx.sampleRate * 0.02));
      for (let off = 0; off < data.length; off += frameSize) {
        const frame = data.slice(off, Math.min(off + frameSize, data.length));
        if (frame.length < frameSize * 0.5) continue;
        processFrame(frame);
      }
    };

    source.connect(proc);
    proc.connect(mute);
    mute.connect(ctx.destination);

    micBtn.classList.add('listening');
    micBtn.title = t('mic.stopContinuous');
    continuousToggle.checked = true;
    hintEl.textContent = t(
      nativeToggle.checked ? 'hint.continuousNative' : 'hint.continuous'
    );
    setStatus('listening', ' · ' + t('status.calibrating'));
  } catch (err) {
    if (ctx) { try { ctx.close(); } catch { /* noop */ } }
    toast(t('toast.continuous', { err: err.message || err }));
    continuousToggle.checked = false;
    setStatus('idle');
  }
}

function stopContinuous() {
  if (!cont.active) return;
  try { cont.proc.disconnect(); } catch { /* noop */ }
  try { cont.source.disconnect(); } catch { /* noop */ }
  try { cont.mute.disconnect(); } catch { /* noop */ }
  try { cont.stream.getTracks().forEach((t) => t.stop()); } catch { /* noop */ }
  try { cont.ctx.close(); } catch { /* noop */ }

  Object.assign(cont, {
    active: false,
    paused: false,
    stream: null,
    ctx: null,
    source: null,
    proc: null,
    mute: null,
    state: 'idle',
    voiceRun: 0,
    silenceRun: 0,
    segment: [],
    preRoll: [],
  });

  micBtn.classList.remove('listening');
  micBtn.title = '';
  continuousToggle.checked = false;
  hintEl.textContent = defaultHint();
  setStatus('idle');
}

function resetVad() {
  cont.state = 'idle';
  cont.voiceRun = 0;
  cont.silenceRun = 0;
  cont.segment = [];
  cont.preRoll = [];
}

function pauseListening() {
  if (!cont.active) return;
  cont.paused = true;
  resetVad();
}

function resumeListening() {
  if (!cont.active) return;
  cont.paused = false;
  resetVad();
  cont.resumeAt = performance.now() + 400; // ignore the speaker's tail
  setStatus('listening', ' · ' + t('status.speakNow'));
}

function processFrame(frame) {
  if (!cont.active || cont.paused) return;
  if (cont.resumeAt && performance.now() < cont.resumeAt) return;

  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  const rms = Math.sqrt(sum / frame.length);

  if (cont.calibFrames < cont.calibNeeded) {
    cont.calibSum += rms;
    cont.calibFrames += 1;
    if (cont.calibFrames >= cont.calibNeeded) {
      cont.noiseFloor = Math.max(0.002, cont.calibSum / cont.calibNeeded);
      cont.threshold = Math.min(0.06, Math.max(0.006, cont.noiseFloor * 3));
      cont.preRoll = [];
      setStatus('listening', ' · ' + t('status.speakNow'));
    }
    return;
  }

  if (cont.state === 'idle') {
    cont.preRoll.push(frame);
    if (cont.preRoll.length > 25) cont.preRoll.shift(); // 500ms pre-roll

    if (rms > cont.threshold) {
      cont.voiceRun += 1;
      if (cont.voiceRun >= 3) {
        cont.state = 'speech';
        cont.segment = cont.preRoll.slice();
        cont.preRoll = [];
        cont.silenceRun = 0;
        cont.voiceRun = 0;
        setStatus('listening', ' · ' + t('status.recordingQuestion'));
      }
    } else {
      cont.voiceRun = 0;
      cont.noiseFloor = cont.noiseFloor * 0.98 + rms * 0.02;
      cont.threshold = Math.min(0.06, Math.max(0.006, cont.noiseFloor * 3));
    }
    return;
  }

  if (cont.state === 'speech') {
    cont.segment.push(frame);
    if (rms > cont.threshold) cont.silenceRun = 0;
    else cont.silenceRun += 1;

    const duration = cont.segment.length * 0.02;
    if (cont.silenceRun >= 45 || duration >= 20) finalizeSegment(); // 900ms silence / 20s max
  }
}

function finalizeSegment() {
  const frames = cont.segment;
  const trailing = cont.silenceRun;
  resetVad();

  if (!frames.length) return;

  // Keep at most 300ms of the trailing silence.
  const keep = Math.max(1, frames.length - Math.max(0, trailing - 15));
  const used = frames.slice(0, keep);

  let total = 0;
  for (const f of used) total += f.length;
  const merged = new Float32Array(total);
  let off = 0;
  for (const f of used) {
    merged.set(f, off);
    off += f.length;
  }

  if (merged.length / cont.ctx.sampleRate < 0.4) {
    setStatus('listening', ' · ' + t('status.speakNow'));
    return;
  }

  const pcm = resampleTo16k(merged, cont.ctx.sampleRate);
  const blob = encodeWav(pcm, 16000);
  handleAudio(blob, true);
}

function resampleTo16k(input, inRate) {
  if (inRate === 16000) return input;
  const ratio = inRate / 16000;
  const outLen = Math.max(1, Math.round(input.length / ratio));
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio;
    const i0 = Math.floor(pos);
    const i1 = Math.min(i0 + 1, input.length - 1);
    const frac = pos - i0;
    out[i] = input[i0] * (1 - frac) + input[i1] * frac;
  }
  return out;
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  const writeString = (offset, text) => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  };

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, 'data');
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }
  return new Blob([view], { type: 'audio/wav' });
}

/* ---------- pipeline ---------- */

async function handleAudio(blob, fromContinuous) {
  busy = true;
  if (fromContinuous) pauseListening();
  else micBtn.disabled = true;

  try {
    if (nativeToggle.checked) {
      addUserMessage('🎤 ' + t('mic.voiceInput'), null, true);
      const done = await askNative(blob);
      if (fromContinuous) {
        await done;
        if (cont.active) resumeListening();
      }
      return;
    }

    setStatus('transcribing');
    const fd = new FormData();
    fd.append('audio', blob, 'speech.wav');
    fd.append('language', langSel.value);

    const r = await fetch('/api/transcribe', { method: 'POST', body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || t('error.transcribe'));

    const transcript = (j.transcript || '').trim();
    if (!transcript) {
      toast(t('toast.noSpeech'));
      if (fromContinuous) resumeListening();
      else setStatus('idle');
      return;
    }

    addUserMessage(transcript, j.language);
    const done = await ask(transcript, j.asr_s);
    if (fromContinuous) {
      await done;
      if (cont.active) resumeListening();
    }
  } catch (err) {
    toast(err.message || String(err));
    if (fromContinuous && cont.active) resumeListening();
    else setStatus('idle');
  } finally {
    busy = false;
    if (!fromContinuous) micBtn.disabled = false;
  }
}

async function ask(text, asrS) {
  setStatus('thinking');
  const fd = new FormData();
  fd.append('text', text);
  fd.append('speaker', speakerSel.value);
  fd.append('model', modelSel.value);

  const r = await fetch('/api/answer', { method: 'POST', body: fd });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || t('error.answer'));

  return addAssistantMessage(j, asrS);
}

async function askNative(blob) {
  setStatus('thinking');
  const fd = new FormData();
  fd.append('audio', blob, 'speech.wav');
  fd.append('speaker', speakerSel.value);
  fd.append('language', langSel.value);
  fd.append('model', modelSel.value);
  fd.append('keep_transcript', keepTranscriptToggle.checked ? 'true' : 'false');

  const r = await fetch('/api/answer_audio', { method: 'POST', body: fd });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || t('error.answer'));

  return addAssistantMessage(j, null, true);
}

/* ---------- controls ---------- */

micBtn.addEventListener('click', () => {
  if (cont.active) {
    stopContinuous();
    return;
  }
  if (busy) return;
  if (recording) stopRecording();
  else startRecording();
});

continuousToggle.addEventListener('change', () => {
  if (continuousToggle.checked) startContinuous();
  else stopContinuous();
});

nativeToggle.addEventListener('change', () => {
  // In native mode the selector picks the reply language (auto = follow speech).
  hintEl.textContent = defaultHint();
});

modelSel.addEventListener('change', () => {
  syncModelControls();
  toast(t('toast.modelSwitch'));
});

textForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = textInput.value.trim();
  if (!text || busy) return;
  textInput.value = '';
  addUserMessage(text);

  busy = true;
  if (cont.active) pauseListening();
  else micBtn.disabled = true;

  try {
    const done = await ask(text, null);
    if (cont.active) {
      await done;
      if (cont.active) resumeListening();
    }
  } catch (err) {
    toast(err.message || String(err));
    if (cont.active) resumeListening();
    else setStatus('idle');
  } finally {
    busy = false;
    if (!cont.active) micBtn.disabled = false;
  }
});

document.addEventListener('visibilitychange', () => {
  if (!document.hidden && cont.active && cont.ctx && cont.ctx.state === 'suspended') {
    cont.ctx.resume().catch(() => {});
  }
});

/* ---------- rendering ---------- */

function addUserMessage(text, lang, native = false) {
  removeEmpty();
  const msg = el('div', 'msg user');
  const label = native
    ? `${t('role.you')} · ${t('role.native')}`
    : lang === 'zh'
      ? `${t('role.you')} · ${t('role.zh')}`
      : lang === 'en'
        ? `${t('role.you')} · ${t('role.en')}`
        : t('role.you');
  msg.appendChild(el('div', 'who', label));
  msg.appendChild(el('div', 'bubble', text));
  chat.appendChild(msg);
  scrollToBottom();
}

function stat(label, value) {
  const box = el('div');
  box.appendChild(el('span', null, label));
  box.appendChild(el('b', null, value));
  return box;
}

function weatherCard(w) {
  const card = el('div', 'weather');

  const top = el('div', 'weather-top');
  top.appendChild(
    el('div', 'weather-city', [w.city, w.country].filter(Boolean).join(' · '))
  );
  top.appendChild(el('div', 'weather-cond', w.condition || ''));
  card.appendChild(top);

  card.appendChild(el('div', 'weather-temp', `${w.temperature_c}°C`));

  const grid = el('div', 'weather-grid');
  grid.appendChild(stat(t('weather.feels'), `${w.apparent_temperature_c}°C`));
  grid.appendChild(stat(t('weather.humidity'), `${w.humidity_pct}%`));
  grid.appendChild(stat(t('weather.wind'), `${w.wind_kmh} km/h`));
  card.appendChild(grid);

  return card;
}

function audioRow(j) {
  const row = el('div', 'audio-row');
  const btn = el('button', 'play-btn', t('audio.play'));
  btn.type = 'button';
  row.appendChild(btn);
  row.appendChild(el('span', 'dur', `${Number(j.duration_s).toFixed(2)}s`));

  const audio = new Audio(j.audio);
  let resolveDone;
  const done = new Promise((resolve) => { resolveDone = resolve; });
  let settled = false;
  const finish = () => {
    if (!settled) {
      settled = true;
      resolveDone();
    }
  };

  btn.addEventListener('click', () => {
    if (audio.paused) {
      audio.play().catch(() => toast(t('toast.playBlocked')));
    } else {
      audio.pause();
    }
  });

  audio.onplay = () => {
    btn.textContent = t('audio.pause');
    setStatus('speaking');
    if (cont.active) pauseListening();
  };
  audio.onpause = () => {
    btn.textContent = audio.ended ? t('audio.replay') : t('audio.resume');
  };
  audio.onended = () => {
    btn.textContent = t('audio.replay');
    if (cont.active) resumeListening();
    else setStatus('idle');
    finish();
  };
  audio.onerror = () => finish();

  setStatus('speaking');
  audio.play().catch(() => {
    if (cont.active) resumeListening();
    else setStatus('idle');
    finish();
  });

  return { row, done };
}

function timingText(j, asrS) {
  const times = j.timings || {};
  const parts = [];
  if (asrS != null) parts.push(t('timing.asr', { v: Number(asrS).toFixed(1) }));
  if (times.probe_s != null) parts.push(t('timing.lang', { v: Number(times.probe_s).toFixed(1) }));
  if (times.decide_s != null) parts.push(t('timing.decide', { v: Number(times.decide_s).toFixed(1) }));
  if (times.tool_s != null) parts.push(t('timing.tool', { v: Number(times.tool_s).toFixed(2) }));
  if (times.speech_s != null) parts.push(t('timing.speech', { v: Number(times.speech_s).toFixed(1) }));
  return parts.join(' · ');
}

function flightCard(f) {
  const card = el('div', 'tool-card');

  const top = el('div', 'tool-top');
  top.appendChild(el('div', 'tool-title', `✈️ ${f.callsign || t('flight.fallback')}`));
  top.appendChild(el('div', 'tool-sub', f.found
    ? [f.aircraft_type, f.registration].filter(Boolean).join(' · ')
    : t('flight.noSignal')));
  card.appendChild(top);

  if (!f.found) {
    card.appendChild(el('div', 'tool-note', f.note || t('flight.noSignalNote')));
    return card;
  }

  const grid = el('div', 'tool-grid');
  grid.appendChild(stat(t('flight.altitude'), f.altitude_ft != null
    ? `${f.altitude_ft} ft · ${f.altitude_m} m` : '—'));
  grid.appendChild(stat(t('flight.groundSpeed'), f.ground_speed_kmh != null
    ? `${f.ground_speed_kmh} km/h` : '—'));
  grid.appendChild(stat(t('flight.heading'), f.heading
    ? `${f.heading} ${Math.round(f.heading_deg)}°` : '—'));
  grid.appendChild(stat(t('flight.position'), f.latitude != null
    ? `${Number(f.latitude).toFixed(2)}, ${Number(f.longitude).toFixed(2)}` : '—'));
  card.appendChild(grid);
  card.appendChild(el('div', 'tool-note', t('flight.source')));
  return card;
}

function timeCard(data) {
  const card = el('div', 'tool-card');

  const top = el('div', 'tool-top');
  top.appendChild(el('div', 'tool-title', `🕒 ${data.city || t('time.local')}`));
  top.appendChild(el('div', 'tool-sub', data.timezone || ''));
  card.appendChild(top);

  const clock = (data.local_time || '').split(' ')[1] || data.local_time || '—';
  card.appendChild(el('div', 'time-big', clock));
  card.appendChild(el('div', 'tool-note',
    `${data.local_time || ''} · ${data.weekday || ''} · UTC${data.utc_offset || ''}`));
  return card;
}

function fxCard(f) {
  const card = el('div', 'tool-card');

  const top = el('div', 'tool-top');
  top.appendChild(el('div', 'tool-title', `💱 ${f.base} → ${f.quote}`));
  top.appendChild(el('div', 'tool-sub', f.date || ''));
  card.appendChild(top);

  card.appendChild(el('div', 'fx-rate', `1 ${f.base} = ${f.rate} ${f.quote}`));
  if (f.inverse_rate != null) {
    card.appendChild(el('div', 'tool-note',
      `1 ${f.quote} = ${f.inverse_rate} ${f.base} · ${t('fx.ecb')}`));
  }
  return card;
}

function wikiCard(w) {
  const card = el('div', 'tool-card');

  const top = el('div', 'tool-top');
  top.appendChild(el('div', 'tool-title', `📚 ${w.title || w.topic || t('wiki.fallback')}`));
  top.appendChild(el('div', 'tool-sub', (w.language || '').toUpperCase()));
  card.appendChild(top);

  if (w.extract) card.appendChild(el('div', 'wiki-extract', w.extract));
  if (w.found === false) {
    card.appendChild(el('div', 'tool-note', w.note || t('wiki.notFound')));
  }
  if (w.url) {
    const link = el('a', 'wiki-link', t('wiki.view'));
    link.href = w.url;
    link.target = '_blank';
    link.rel = 'noopener';
    card.appendChild(link);
  }
  return card;
}

function toolCard(tool) {
  const r = tool.result || {};
  if (r.error) return el('div', 'meta', t('tool.failed', { err: r.error }));
  switch (tool.name) {
    case 'get_weather':
      return r.city ? weatherCard(r) : el('div', 'meta', t('weather.unavailable'));
    case 'get_flight': return flightCard(r);
    case 'get_time': return timeCard(r);
    case 'get_exchange_rate': return fxCard(r);
    case 'get_wikipedia': return wikiCard(r);
    default: return el('div', 'meta', JSON.stringify(r).slice(0, 240));
  }
}

function addAssistantMessage(j, asrS, native = false) {
  removeEmpty();
  const msg = el('div', 'msg assistant');
  const label = j.model === 'minicpm' ? 'MiniCPM-o 4.5' : 'Qwen3-Omni';
  msg.appendChild(el('div', 'who', native ? `${label} · ${t('role.native')}` : label));

  const bubble = el('div', 'bubble');

  const tool = j.tool || (j.tool_call
    ? { name: j.tool_call.name, arguments: j.tool_call.arguments || {}, result: j.weather }
    : null);

  if (tool) {
    const args = JSON.stringify(tool.arguments || {});
    bubble.appendChild(el('div', 'tool-chip', `🔧 ${tool.name}(${args})`));
  }

  bubble.appendChild(el('div', null, j.answer || t('assistant.empty')));

  if (tool) bubble.appendChild(toolCard(tool));

  const { row, done } = audioRow(j);
  bubble.appendChild(row);
  msg.appendChild(bubble);

  const meta = timingText(j, asrS);
  if (meta) msg.appendChild(el('div', 'meta', meta));

  chat.appendChild(msg);
  scrollToBottom();
  checkHealth();
  return done;
}

window.addEventListener('omnivoice:lang', () => {
  syncModelControls();
  setStatus(statusEl.dataset.state || 'idle');
  checkHealth();
});

syncModelControls();
checkHealth();
