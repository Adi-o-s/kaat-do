// Debrief voice note and the result card. No score: one verdict and the facts behind it.
(() => {
  const KD = window.KD;
  const $ = (s) => document.querySelector(s);
  const ORD = ["red flag se pehle hi", "pehle red flag pe", "doosre red flag pe", "teesre red flag pe", "chauthe red flag pe"];
  const SLIP_TEXT = { otp: "OTP bata diya", paisa: "Paise ya code ki baat pe haan kaha", raaz: "\"Kisi ko mat batana\" pe haan kaha" };

  function verdictOf(results) {
    const scams = results.filter((r) => r.call.scam);
    const genuine = results.filter((r) => !r.call.scam);
    if (scams.some((r) => r.outcome === "otp" || r.outcome === "ran")) return "phans";
    const slips = scams.some((r) => r.slips.length);
    const cutGenuine = genuine.some((r) => r.outcome === "cut_genuine");
    return !slips && !cutGenuine ? "pakka" : "bach";
  }

  function lineFor(r) {
    const n = r.call.name;
    switch (r.outcome) {
      case "cut": return `${n}: kaata, ${ORD[Math.min(r.flagsHeard, 4)]}, ${r.seconds} second`;
      case "otp": return `${n}: OTP bata diya`;
      case "ran": return `${n}: call aakhir tak chali`;
      case "completed": return `${n}: asli call thi, poori suni. Sahi.`;
      case "cut_genuine": return `${n}: asli call kaat di. Isne kuch nahi maanga tha.`;
    }
    return n;
  }

  function pickDebrief(results, personal) {
    const all = (k) => results.flatMap((r) => r[k]);
    const good = all("good");
    const slips = all("slips");
    const scams = results.filter((r) => r.call.scam);
    let praise = "praise_default";
    if (good.some((g) => g.kind === "verify")) praise = "praise_verify";
    else if (good.some((g) => g.kind === "push")) praise = "praise_push";
    else if (scams.length && scams.every((r) => r.outcome === "cut")) praise = "praise_cut";

    let slip = "slip_none", evidence = null;
    const find = (k) => slips.find((s) => s.kind === k);
    if (find("otp")) { slip = "slip_otp"; evidence = find("otp"); }
    else if (find("paisa")) { slip = "slip_paisa"; evidence = find("paisa"); }
    else if (find("raaz")) { slip = "slip_raaz"; evidence = find("raaz"); }
    else if (results.some((r) => r.outcome === "ran")) slip = "slip_ran";
    else if (results.some((r) => r.outcome === "cut_genuine")) slip = "slip_genuine";
    const praiseEvidence = good.find((g) => (praise === "praise_verify" ? g.kind === "verify" : g.kind === "push"));
    return { keys: [praise, slip, "rule", personal ? "reveal" : "warning"], evidence, praiseEvidence };
  }

  KD.debrief = async function (S) {
    const { script, results } = S;
    const verdict = verdictOf(results);
    const plan = pickDebrief(results, script.personal);
    KD.show("debrief");
    $("#vnFrom").textContent = script.personal ? (script.child_name || "Aapka bachcha") : "Kaat Do coach";
    const list = $("#vnLines");
    list.innerHTML = "";
    const lines = plan.keys.map((k) => script.debrief[k]).filter(Boolean);
    lines.forEach((l, i) => {
      const p = document.createElement("p");
      p.textContent = l.en;
      p.id = "vn" + i;
      if (l.id.endsWith("praise_verify") || l.id.endsWith("praise_push")) {
        if (plan.praiseEvidence && !plan.praiseEvidence.words.startsWith("[tap]")) appendWords(p, plan.praiseEvidence.words);
      }
      if (l.id.includes("slip_") && plan.evidence && !plan.evidence.words.startsWith("[tap]")) appendWords(p, plan.evidence.words);
      list.appendChild(p);
    });
    const play = async () => {
      $("#vnPlay").disabled = true;
      for (let i = 0; i < lines.length; i++) {
        document.querySelectorAll("#vnLines p").forEach((x, j) => x.classList.toggle("now", j === i));
        $("#vnBar").style.width = `${((i + 0.5) / lines.length) * 100}%`;
        await KD.audio.play(lines[i]);
      }
      $("#vnBar").style.width = "100%";
      document.querySelectorAll("#vnLines p").forEach((x) => x.classList.remove("now"));
      $("#vnPlay").disabled = false;
      $("#vnPlay").textContent = "▶ Phir se sunein";
      $("#toCard").classList.add("ready");
    };
    $("#vnPlay").onclick = play;
    $("#toCard").onclick = () => showCard(S, verdict);
    await KD.sleep(500);
    play();
  };

  function appendWords(p, words) {
    const q = document.createElement("span");
    q.className = "said";
    q.textContent = `Aapne kaha: "${words}"`;
    p.appendChild(q);
  }

  async function showCard(S, verdict) {
    const { script, results } = S;
    KD.audio.stop();
    KD.show("card");
    const V = { pakka: ["Pakka", "Har scam kaata, asli call nahi kaati."], bach: ["Bach gaye", "Har scam kaata, par raste mein ek chook hui."], phans: ["Phans gaye", "Is baar ek scam nikal gaya. Isi liye practice hai."] }[verdict];
    $("#cardVerdict").textContent = V[0];
    $("#cardVerdict").className = "verdict " + verdict;
    $("#cardSub").textContent = V[1];
    const ul = $("#cardCalls");
    ul.innerHTML = "";
    results.forEach((r) => {
      const li = document.createElement("li");
      li.className = r.outcome;
      const head = document.createElement("div");
      head.textContent = lineFor(r);
      li.appendChild(head);
      if (r.slips.length) {
        const d = document.createElement("details");
        const s = document.createElement("summary");
        s.textContent = "Kya suna gaya";
        d.appendChild(s);
        r.slips.forEach((sl) => {
          const p = document.createElement("p");
          p.textContent = `${SLIP_TEXT[sl.kind] || sl.kind}: "${sl.words.replace(/^\[tap\] /, "")}"`;
          d.appendChild(p);
        });
        li.appendChild(d);
      }
      ul.appendChild(li);
    });
    if (results.some((r) => r.mode === "tap")) $("#cardMode").textContent = "Tap mode mein kiya gaya.";
    const cuts = results.filter((r) => r.call.scam && r.outcome === "cut").map((r) => r.seconds);
    const fastest = cuts.length ? Math.min(...cuts) : null;
    $("#cardFast").textContent = fastest !== null ? `Sabse tez cut: ${fastest} second` : "";

    const who = script.parent_word || "Mere parent";
    const vWord = V[0];
    let resultUrl = location.origin + "/";
    try {
      const r = await fetch("/api/result", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdict, fastest, parent_word: script.parent_word, personal: script.personal,
          mode: S.mode, calls: results.map((r) => ({ id: r.call.id, outcome: r.outcome, line: lineFor(r) })) }),
      });
      if (r.ok) resultUrl = location.origin + (await r.json()).url;
    } catch (e) {}
    const shareText = script.personal
      ? `${script.child_name || ""}, maine Kaat Do practice kiya: ${vWord}${fastest !== null ? `, sabse tez cut ${fastest} second` : ""}. ${resultUrl}`
      : `Kaat Do scam practice: ${vWord}${fastest !== null ? `, ${fastest} second mein scam kaata` : ""}. Aapke parents kar payenge? ${location.origin}/`;
    $("#shareBtn").textContent = script.personal ? `${script.child_name || "Bachche"} ko result bhejein` : "Result share karein";
    $("#shareBtn").onclick = async () => {
      if (navigator.share) { try { await navigator.share({ text: shareText }); return; } catch (e) {} }
      window.open("https://wa.me/?text=" + encodeURIComponent(shareText), "_blank");
    };
    $("#againBtn").onclick = () => location.reload();
  }

  KD.verdictOf = verdictOf;
  KD.lineFor = lineFor;
  KD.pickDebrief = pickDebrief;
})();
