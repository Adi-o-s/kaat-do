// Kaat Do call state machine. All call state lives in the page; the server only
// transcribes and sorts one reply at a time.
(() => {
  const KD = window.KD;
  const A = KD.audio;
  const qs = new URLSearchParams(location.search);
  const $ = (s) => document.querySelector(s);

  const S = (KD.state = {
    script: null,
    order: [],
    mode: "mic", // or "tap"
    captions: qs.get("captions") === "1",
    results: [],
    ctx: null,
    preloaded: false,
  });

  class HangUp extends Error {}

  function show(id) {
    document.querySelectorAll(".screen").forEach((el) => el.classList.toggle("on", el.id === id));
  }

  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a;
  }

  function newOtp() {
    let s = "";
    for (let i = 0; i < 6; i++) s += Math.floor(Math.random() * 10);
    return s[0] === "0" ? "7" + s.slice(1) : s;
  }

  function fmt(sec) { sec = Math.floor(sec); return `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`; }

  function caption(who, text) {
    if (!S.captions || !text) return;
    const box = $("#captions");
    const p = document.createElement("div");
    p.className = "cap " + who;
    p.textContent = text;
    box.appendChild(p);
    box.scrollTop = box.scrollHeight;
  }

  function status(t) { $("#callStatus").textContent = t || ""; }

  // ---------------------------------------------------------------- boot
  async function boot() {
    const d = qs.get("d");
    try {
      const r = await fetch("/api/script" + (d ? "?d=" + encodeURIComponent(d) : ""));
      if (!r.ok) throw new Error((await r.json()).detail || "Link not found");
      S.script = await r.json();
    } catch (e) {
      $("#ringIntro").textContent = "Yeh practice link khul nahi raha. " + e.message;
      return;
    }
    const calls = S.script.calls.filter((c) => !c.clone_only);
    S.order = shuffle(calls.slice());
    const clone = S.script.calls.find((c) => c.clone_only);
    if (clone) S.order.push(clone);
    if (S.script.personal) {
      document.body.classList.add("personal");
      $("#fromLine").textContent = `${S.script.child_name || "Aapke bachche"} ne yeh practice bheji hai.`;
    }
    runDrill();
  }

  async function preload() {
    if (S.preloaded) return;
    S.preloaded = true;
    const urls = new Set();
    const add = (l) => l && l.src && urls.add(l.src);
    S.script.calls.forEach((c) => { c.stages.forEach((s) => { add(s.line); add(s.pressure); }); add(c.end); add(c.otp_thanks); });
    Object.values(S.script.fillers).forEach(add);
    Object.values(S.script.nudges).forEach(add);
    Object.values(S.script.debrief).forEach(add);
    urls.forEach((u) => A.load(u));
  }

  async function runDrill() {
    for (let i = 0; i < S.order.length; i++) {
      const res = await runCall(S.order[i], i);
      S.results.push(res);
      if (i < S.order.length - 1) {
        show("between");
        $("#betweenText").textContent = res.call.scam === false && res.outcome === "completed"
          ? "Call khatam hui. Agli call aa rahi hai..."
          : "Agli call aa rahi hai...";
        await sleep(2600);
      }
    }
    KD.debrief(S);
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---------------------------------------------------------------- one call
  function waitRing(call, index) {
    return new Promise((resolve) => {
      show("ring");
      $("#ringName").textContent = call.clone_only ? "Unknown number" : call.caller;
      $("#ringSub").textContent = call.clone_only ? "Incoming call · Naya number" : "Incoming call · Mobile";
      $("#ringIntro").style.display = index === 0 ? "" : "none";
      $("#ringCount").textContent = `Practice call ${index + 1} / ${S.order.length}`;
      const tone = index === 0 ? { stop() {} } : A.ring();
      if (navigator.vibrate) try { navigator.vibrate([400, 200, 400]); } catch (e) {}
      const done = (answered) => { tone.stop(); $("#answer").onclick = $("#decline").onclick = null; resolve(answered); };
      $("#answer").onclick = () => done(true);
      $("#decline").onclick = () => done(false);
    });
  }

  async function runCall(call, index) {
    const answered = await waitRing(call, index);
    const ctx = (S.ctx = {
      call, index, ended: false, endedBy: null, t0: performance.now(), stage: 0, flagsHeard: 0,
      slips: [], good: [], heard: [], turns: 0, otp: newOtp(), smsShown: false, tapResolve: null,
    });
    const result = (outcome) => ({
      call: { id: call.id, name: call.name, scam: call.scam, clone_only: !!call.clone_only },
      outcome,
      stage: call.stages[ctx.stage] ? call.stages[ctx.stage].id : null,
      flagsHeard: ctx.flagsHeard,
      seconds: Math.round((performance.now() - ctx.t0) / 1000),
      slips: ctx.slips, good: ctx.good, heard: ctx.heard, mode: S.mode,
    });

    if (index === 0) {
      await A.unlock();
      preload();
      const micOk = S.script.stt && (await A.openMic());
      S.mode = micOk ? "mic" : "tap";
    }
    if (!answered) {
      ctx.t0 = performance.now();
      return result(call.scam ? "cut" : "cut_genuine");
    }

    show("call");
    document.body.classList.toggle("tap", S.mode === "tap");
    $("#callName").textContent = call.clone_only ? "Unknown number" : call.caller;
    $("#captions").innerHTML = "";
    $("#sms").classList.remove("on");
    $("#debit").classList.remove("on");
    $("#modeTag").textContent = S.mode === "tap" ? "Tap mode" : "";
    const timer = setInterval(() => { $("#callTimer").textContent = fmt((performance.now() - ctx.t0) / 1000); }, 500);
    $("#callTimer").textContent = "00:00";

    $("#hangup").onclick = () => hangUp(ctx, "button");

    let outcome;
    try {
      outcome = await converse(ctx);
    } catch (e) {
      if (!(e instanceof HangUp)) console.error(e);
      outcome = call.scam ? "cut" : "cut_genuine";
    } finally {
      clearInterval(timer);
      A.stop();
      A.stopListening();
      setTaps(null);
    }
    const r = result(outcome);
    if (outcome === "otp" || (outcome === "ran" && call.clone_only)) {
      $("#debit").textContent = "PRACTICE · " + (call.debit || "Paisa chala gaya");
      $("#debit").classList.add("on");
      await sleep(2200);
    } else {
      status(outcome === "cut" || outcome === "cut_genuine" ? "Call kaat di" : "Call khatam");
      await sleep(900);
    }
    return r;
  }

  function hangUp(ctx, by) {
    if (ctx.ended) return;
    ctx.ended = true;
    ctx.endedBy = by;
    A.stop();
    A.stopListening();
    if (ctx.tapResolve) ctx.tapResolve(null);
  }

  function check(ctx) { if (ctx.ended) throw new HangUp(); }

  async function say(ctx, line) {
    check(ctx);
    caption("caller", line.en);
    status("");
    await A.play(line);
    check(ctx);
  }

  async function converse(ctx) {
    const { call } = ctx;
    for (let i = 0; i < call.stages.length; i++) {
      const st = call.stages[i];
      ctx.stage = i;
      if (st.flag) ctx.flagsHeard++;
      if (st.sms && call.sms) showSms(ctx);
      await say(ctx, st.line);
      let pressured = false, nudges = 0;
      for (;;) {
        if (ctx.turns >= call.max_turns || (performance.now() - ctx.t0) / 1000 > call.max_seconds) {
          await say(ctx, call.end);
          return call.scam ? "ran" : "completed";
        }
        const reply = await getReply(ctx, st);
        ctx.turns++;
        if (reply.transcript) ctx.heard.push({ stage: st.id, words: reply.transcript, kind: reply.kind });
        if (reply.kind === "hangup") { hangUp(ctx, "spoken"); check(ctx); }
        if (reply.kind === "otp") {
          ctx.slips.push({ kind: "otp", stage: st.id, words: reply.transcript });
          if (call.otp_thanks) await say(ctx, call.otp_thanks);
          return "otp";
        }
        if (reply.kind === "agree") {
          if (call.scam && (st.flag === "raaz" || st.flag === "paisa")) {
            ctx.slips.push({ kind: st.flag, stage: st.id, words: reply.transcript });
          }
          break;
        }
        if (reply.kind === "push" || reply.kind === "verify") {
          ctx.good.push({ kind: reply.kind, stage: st.id, words: reply.transcript });
          if (!pressured && st.pressure) { pressured = true; await say(ctx, st.pressure); continue; }
          break;
        }
        // unclear or silent: never a slip
        if (nudges < 2) { nudges++; await say(ctx, nudgeFor(st)); continue; }
        break;
      }
    }
    await say(ctx, call.end);
    return call.scam ? "ran" : "completed";
  }

  function nudgeFor(st) { return S.script.nudges[st.line.voice] || Object.values(S.script.nudges)[0]; }
  function fillerFor(st) { return S.script.fillers[st.line.voice]; }

  function showSms(ctx) {
    ctx.smsShown = true;
    const el = $("#sms");
    $("#smsFrom").textContent = ctx.call.sms.from;
    const [pre, post] = ctx.call.sms.text.split("{OTP}");
    const t = $("#smsText");
    t.textContent = "";
    const b = document.createElement("b");
    b.textContent = ctx.otp;
    t.append(pre || "", b, post || "");
    el.classList.add("on");
  }

  // ---------------------------------------------------------------- replies
  async function getReply(ctx, st) {
    if (S.mode === "tap") return tapReply(ctx);
    status("Aap boliye...");
    $("#callScreen").classList.add("listening");
    const rec = await A.listen({ onLevel: setBars });
    $("#callScreen").classList.remove("listening");
    setBars(0);
    check(ctx);
    if (!rec) return { kind: "unclear", transcript: "" };
    status("");
    const filler = fillerFor(st);
    const fillP = filler ? A.play(filler) : Promise.resolve();
    const fd = new FormData();
    fd.append("audio", rec.wav, "reply.wav");
    fd.append("otp", ctx.smsShown ? ctx.otp : "");
    fd.append("call", ctx.call.id);
    fd.append("stage", st.id);
    let out = { kind: "unclear", transcript: "" };
    try {
      const ctl = new AbortController();
      const to = setTimeout(() => ctl.abort(), 9000);
      const r = await fetch("/api/turn", { method: "POST", body: fd, signal: ctl.signal });
      clearTimeout(to);
      if (r.status === 503) {
        switchToTap();
        await fillP; check(ctx);
        return tapReply(ctx);
      }
      out = await r.json();
    } catch (e) { /* network trouble counts as a bad line */ }
    await fillP;
    check(ctx);
    caption("me", out.transcript || "…");
    return { kind: out.kind || "unclear", transcript: out.transcript || "" };
  }

  const BAR_SHAPE = [0.45, 0.7, 0.9, 1, 0.9, 0.7, 0.45];
  function setBars(l) {
    document.querySelectorAll(".bars i").forEach((b, i) => {
      const jitter = l > 0.05 ? 0.75 + Math.random() * 0.5 : 1;
      b.style.height = `${Math.round(8 + l * 26 * BAR_SHAPE[i] * jitter)}px`;
    });
  }

  function switchToTap() {
    S.mode = "tap";
    document.body.classList.add("tap");
    $("#modeTag").textContent = "Tap mode";
  }

  const TAPS = [
    { kind: "agree", label: "Haan ji" },
    { kind: "push", label: "Nahi" },
    { kind: "push", label: "Aap kaun bol rahe ho?" },
    { kind: "verify", label: "Pehle ghar pe poochunga" },
  ];

  function setTaps(list) {
    const box = $("#taps");
    box.innerHTML = "";
    if (!list) return;
    list.forEach((t) => {
      const b = document.createElement("button");
      b.className = "tapbtn" + (t.kind === "otp" ? " otp" : "");
      b.textContent = t.label;
      b.onclick = () => t.pick();
      box.appendChild(b);
    });
  }

  function tapReply(ctx) {
    status("Jawab chuniye");
    return new Promise((resolve) => {
      const opts = TAPS.map((t) => ({ ...t }));
      if (ctx.smsShown) opts.push({ kind: "otp", label: `Code bata do: ${ctx.otp}` });
      const finish = (v) => { ctx.tapResolve = null; setTaps(null); resolve(v); };
      opts.forEach((o) => (o.pick = () => { caption("me", o.label); finish({ kind: o.kind, transcript: "[tap] " + o.label }); }));
      ctx.tapResolve = () => finish({ kind: "unclear", transcript: "" });
      setTaps(opts);
    }).then((v) => { check(ctx); return v; });
  }

  KD.show = show;
  KD.sleep = sleep;
  window.addEventListener("DOMContentLoaded", boot);
})();
