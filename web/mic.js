// Audio in and out for Kaat Do.
// One AudioContext, unlocked by the "answer" tap. Caller clips play through it.
// The microphone is opened once but only listened to between caller lines
// (half duplex), and each reply is turned into a 16 kHz mono WAV in the page,
// because Prisma REST does not accept the WebM/MP4 that browsers record.

const KD = (window.KD = window.KD || {});

KD.audio = {
  ctx: null,
  stream: null,
  source: null,
  proc: null,
  buffers: new Map(),
  current: null,
  listening: null,
  bandpass: null,

  async unlock() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC();
    }
    if (this.ctx.state === "suspended") await this.ctx.resume();
    // iOS needs a sound started inside the gesture
    const b = this.ctx.createBuffer(1, 1, 22050);
    const s = this.ctx.createBufferSource();
    s.buffer = b; s.connect(this.ctx.destination); s.start(0);
  },

  async load(url) {
    if (!url) return null;
    if (this.buffers.has(url)) return this.buffers.get(url);
    const p = fetch(url).then((r) => {
      if (!r.ok) throw new Error("missing " + url);
      return r.arrayBuffer();
    }).then((ab) => new Promise((res, rej) => this.ctx.decodeAudioData(ab, res, rej)))
      .catch(() => null);
    this.buffers.set(url, p);
    return p;
  },

  // Play a line. Uses the rendered clip, or the browser voice if the clip is missing.
  // Resolves when it ends or is stopped.
  async play(line) {
    this.stop();
    const buf = line.src ? await this.load(line.src) : null;
    if (buf) {
      return new Promise((resolve) => {
        const s = this.ctx.createBufferSource();
        s.buffer = buf;
        s.connect(this.ctx.destination);
        s.onended = () => { if (this.current === s) this.current = null; resolve(); };
        this.current = s;
        s.start(0);
      });
    }
    return this.speak(line.hi);
  },

  speak(text) {
    return new Promise((resolve) => {
      if (!("speechSynthesis" in window)) return setTimeout(resolve, 1200);
      const clean = text.replace(/<[^>]+>/g, "").replace(/\{P\}/g, "");
      const u = new SpeechSynthesisUtterance(clean);
      u.lang = "hi-IN";
      u.rate = 1.05;
      const v = speechSynthesis.getVoices().find((x) => x.lang && x.lang.startsWith("hi"));
      if (v) u.voice = v;
      const safety = setTimeout(resolve, 1500 + clean.length * 70); // some browsers never fire onend
      u.onend = u.onerror = () => { clearTimeout(safety); resolve(); };
      this.current = { stop: () => { clearTimeout(safety); speechSynthesis.cancel(); resolve(); } };
      speechSynthesis.speak(u);
    });
  },

  stop() {
    const c = this.current;
    this.current = null;
    if (c) { try { c.stop(); } catch (e) {} }
    if ("speechSynthesis" in window) speechSynthesis.cancel();
  },

  // Indian ring-back style ringtone, generated (no file).
  ring() {
    if (!this.ctx || this.ctx.state !== "running") return { stop() {} };
    const ctx = this.ctx;
    const gain = ctx.createGain();
    gain.gain.value = 0;
    gain.connect(ctx.destination);
    const o1 = ctx.createOscillator(); o1.frequency.value = 400;
    const o2 = ctx.createOscillator(); o2.frequency.value = 450;
    o1.connect(gain); o2.connect(gain); o1.start(); o2.start();
    let t = ctx.currentTime + 0.05;
    for (let i = 0; i < 12; i++) {
      gain.gain.setValueAtTime(0.12, t); gain.gain.setValueAtTime(0, t + 0.4);
      gain.gain.setValueAtTime(0.12, t + 0.6); gain.gain.setValueAtTime(0, t + 1.0);
      t += 3.0;
    }
    return { stop() { try { o1.stop(); o2.stop(); gain.disconnect(); } catch (e) {} } };
  },

  async openMic() {
    if (this.stream) return true;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return false;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (e) {
      return false;
    }
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.proc = this.ctx.createScriptProcessor(2048, 1, 1);
    const mute = this.ctx.createGain(); mute.gain.value = 0;
    this.source.connect(this.proc); this.proc.connect(mute); mute.connect(this.ctx.destination);
    this.proc.onaudioprocess = (e) => { if (this.listening) this.listening(e.inputBuffer.getChannelData(0)); };
    return true;
  },

  // Listen for one reply. Resolves {wav, speechMs} or null if nothing was said.
  // Ends after 0.9 s of quiet once speech started, 12 s of speech, or 7 s of silence.
  listen({ quietMs = 900, maxSpeechMs = 12000, noSpeechMs = 7000, onLevel } = {}) {
    const rate = this.ctx.sampleRate;
    return new Promise((resolve) => {
      const chunks = [];
      const pre = []; // ~300 ms pre-roll
      let started = false, quiet = 0, speech = 0, waited = 0, loud = 0;
      let floor = null, calib = 0;
      const finish = (ok) => {
        this.listening = null;
        this.cancelListen = null;
        if (!ok || !started) return resolve(null);
        resolve({ wav: encodeWav(downsample(concat(chunks), rate, 16000), 16000), speechMs: speech });
      };
      this.cancelListen = () => finish(false);
      this.listening = (data) => {
        const ms = (data.length / rate) * 1000;
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        const rms = Math.sqrt(sum / data.length);
        if (calib < 250) { floor = floor === null ? rms : Math.min(floor, rms); calib += ms; }
        const thr = Math.max(0.012, (floor || 0.004) * 3.2);
        if (onLevel) onLevel(Math.min(1, rms / (thr * 3)));
        const copy = new Float32Array(data);
        if (!started) {
          pre.push(copy); if (pre.length > Math.ceil(300 / ms)) pre.shift();
          waited += ms;
          loud = rms > thr ? loud + 1 : 0;
          if (loud >= 2) { started = true; chunks.push(...pre); }
          else if (waited > noSpeechMs) return finish(false);
          return;
        }
        chunks.push(copy);
        speech += ms;
        quiet = rms > thr * 0.8 ? 0 : quiet + ms;
        if (quiet >= quietMs || speech >= maxSpeechMs) finish(true);
      };
    });
  },

  stopListening() { if (this.cancelListen) this.cancelListen(); },
};

function concat(arrs) {
  const n = arrs.reduce((a, b) => a + b.length, 0);
  const out = new Float32Array(n);
  let o = 0;
  for (const a of arrs) { out.set(a, o); o += a.length; }
  return out;
}

function downsample(buf, from, to) {
  if (from === to) return buf;
  const ratio = from / to;
  const n = Math.floor(buf.length / ratio);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const start = Math.floor(i * ratio), end = Math.min(buf.length, Math.floor((i + 1) * ratio));
    let s = 0;
    for (let j = start; j < end; j++) s += buf[j];
    out[i] = s / Math.max(1, end - start);
  }
  return out;
}

function encodeWav(samples, rate) {
  const pad = Math.floor(rate * 0.25); // silence padding helps very short replies
  const total = samples.length + pad * 2;
  const buf = new ArrayBuffer(44 + total * 2);
  const v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + total * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, total * 2, true);
  let o = 44 + pad * 2;
  for (let i = 0; i < samples.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

KD.encodeWav = encodeWav;
KD.downsample = downsample;
KD.concat = concat;
