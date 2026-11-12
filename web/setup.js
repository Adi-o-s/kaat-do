(() => {
  const A = window.KD.audio;
  const $ = (s) => document.querySelector(s);
  let parent = null, wav = null, recording = false, chunks = [], t0 = 0, tick = null;

  async function init() {
    const cfg = await fetch("/api/config").then((r) => r.json());
    $("#consent").textContent = cfg.consent;
    if (!cfg.clone_call) { $("#cloneCall").checked = false; $("#cloneCall").parentElement.style.display = "none"; }
    if (!cfg.clone) {
      $("#err").textContent = "Personalised drills are paused right now. The sample drill still works.";
      $("#recBtn").disabled = true;
    }
    cfg.parent_words.forEach((w) => {
      const b = document.createElement("button");
      b.className = "chip"; b.textContent = w;
      b.onclick = () => { parent = w; document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c === b)); ready(); };
      $("#who").appendChild(b);
    });
    $("#name").oninput = ready;
    $("#recBtn").onclick = toggleRec;
    $("#makeBtn").onclick = make;
  }

  function ready() { $("#makeBtn").disabled = !(wav && parent && $("#name").value.trim()); }

  async function toggleRec() {
    $("#err").textContent = "";
    if (recording) return stopRec();
    await A.unlock();
    if (!(await A.openMic())) { $("#err").textContent = "Microphone blocked. Open this page in Chrome or Safari and allow the mic."; return; }
    chunks = []; recording = true; t0 = performance.now();
    A.listening = (d) => chunks.push(new Float32Array(d));
    $("#recBtn").textContent = "Stop";
    $("#recBtn").classList.add("on");
    $("#recInfo").textContent = "Recording. Read the whole passage, then stop.";
    tick = setInterval(() => {
      const s = (performance.now() - t0) / 1000;
      $("#recTime").textContent = `0:${String(Math.floor(s)).padStart(2, "0")}`;
      if (s >= 29) stopRec();
    }, 250);
  }

  function stopRec() {
    recording = false; A.listening = null; clearInterval(tick);
    const secs = (performance.now() - t0) / 1000;
    $("#recBtn").textContent = "Again";
    $("#recBtn").classList.remove("on");
    if (secs < 10) { wav = null; $("#err").textContent = "That was short. Please read the whole sentence (about 20 seconds)."; ready(); return; }
    const pcm = window.KD.downsample(window.KD.concat(chunks), A.ctx.sampleRate, 16000);
    wav = window.KD.encodeWav(pcm, 16000);
    $("#recInfo").textContent = `Recorded. Tap Again to redo it.`;
    ready();
  }

  async function make() {
    $("#makeBtn").disabled = true;
    $("#err").textContent = "";
    $("#form").style.display = "none"; $("#making").style.display = "";
    $("#makingInfo").textContent = "Checking the consent sentence…";
    const fd = new FormData();
    fd.append("audio", wav, "consent.wav");
    fd.append("child_name", $("#name").value.trim());
    fd.append("parent_word", parent);
    fd.append("clone_call", $("#cloneCall").checked ? "1" : "0");
    let drill;
    try {
      const r = await fetch("/api/drill", { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || j.error || "Something went wrong");
      drill = j;
    } catch (e) {
      $("#making").style.display = "none"; $("#form").style.display = "";
      $("#err").textContent = e.message; $("#makeBtn").disabled = false;
      return;
    }
    $("#makingTitle").textContent = "Making the clips in your voice…";
    for (let n = 0; n < drill.clips.length; n++) {
      $("#makingInfo").textContent = `Clip ${n + 1} of ${drill.clips.length}`;
      let ok = false;
      for (let tries = 0; tries < 3 && !ok; tries++) {
        const r = await fetch(`/api/drill/${drill.id}/clip/${n}`, { method: "POST" }).catch(() => null);
        ok = r && r.ok;
        if (!ok) await new Promise((res) => setTimeout(res, 1200));
      }
      if (!ok) { $("#makingInfo").textContent = "The voice service is busy. Please try again in a minute."; return; }
      $("#bar").style.width = `${((n + 1) / drill.clips.length) * 100}%`;
    }
    const url = `${location.origin}/?d=${drill.id}`;
    $("#making").style.display = "none"; $("#done").style.display = "";
    $("#link").textContent = url;
    $("#tryBtn").href = url;
    const msg = `${parent}, maine aapke liye ek practice call bheji hai. Yeh sirf practice hai, isse koi paisa nahi jaata. Link kholiye aur phone uthaiye: ${url}`;
    $("#waBtn").onclick = () => window.open("https://wa.me/?text=" + encodeURIComponent(msg), "_blank");
    $("#copyBtn").onclick = async () => { try { await navigator.clipboard.writeText(url); $("#copyBtn").textContent = "Copied"; } catch (e) {} };
  }

  window.addEventListener("DOMContentLoaded", init);
})();
