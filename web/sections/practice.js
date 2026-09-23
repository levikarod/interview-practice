import { api, esc, mmss } from "../lib.js";

const STAGES = [
  ["transcribing", "Transcribing locally"],
  ["measuring", "Measuring delivery"],
  ["analysing", "Checking against your stories"],
  ["done", "Done"],
];
const STAR = ["situation", "task", "action", "result", "reflection"];

let root;
let state;
const $ = (sel) => root.querySelector(sel);

export async function mount(el) {
  root = el;
  state = { asked: [], question: null, recorder: null, stream: null, chunks: [], ticker: null, stopTimer: null, source: null };
  document.addEventListener("keydown", onKey);
  await renderHome();
}

export function unmount() {
  document.removeEventListener("keydown", onKey);
  teardown();
  document.body.classList.remove("focus");
}

function teardown() {
  clearInterval(state.ticker);
  clearTimeout(state.stopTimer);
  if (state.recorder && state.recorder.state !== "inactive") {
    state.recorder.onstop = null;
    state.recorder.stop();
  }
  state.stream?.getTracks().forEach((t) => t.stop());
  state.source?.close();
  state.recorder = null;
  state.stream = null;
  state.source = null;
}

function onKey(event) {
  if (event.key === "Escape" && document.body.classList.contains("focus")) {
    teardown();
    renderHome();
  }
}

function fail(message) {
  const box = $(".error");
  if (!box) return;
  box.textContent = message;
  box.hidden = false;
}

function statusLine(p) {
  if (!p.ready) return `<p class="status">No CV yet. <a href="#/profile">Upload one</a> to start.</p>`;
  if (p.is_example) return `<p class="status">You're practising on sample data from a fictional engineer. <a href="#/profile">Upload your CV</a> to use your own.</p>`;
  if (p.needs_ingest) return `<p class="status">Your CV is uploaded but the story bank isn't built yet. <a href="#/profile">Finish setup</a>.</p>`;
  if (!p.model_cached) return `<p class="status">Your first answer downloads the speech model (${esc(p.whisper_model)}, about 0.5 GB). That takes a couple of minutes, once.</p>`;
  return "";
}

async function renderHome() {
  document.body.classList.remove("focus");
  const [profile, history, bank] = await Promise.all([
    api("/api/profile"), api("/api/history?limit=1"), api("/api/questions"),
  ]);
  const last = history.runs[0];
  const lastQuestion = last && bank.find((q) => q.id === last.question_id);
  const s = profile.stories || { total: 0, draft: 0, verified: 0 };

  root.innerHTML = `
  <section class="home">
    ${statusLine(profile)}
    <h1 class="page-title">Practice</h1>
    <p class="lede">You get one question and a countdown. Answer out loud; the feedback checks what you said against your own stories.</p>
    <button class="primary big" data-act="start">Start a question</button>
    <dl class="tally">
      <div><dt>Answers given</dt><dd>${history.totals.runs}</dd></div>
      <div><dt>Stories verified</dt><dd>${s.verified} of ${s.total}</dd></div>
      <div><dt>Drafts to check</dt><dd>${s.draft}</dd></div>
    </dl>
    ${lastQuestion ? `
    <div class="last">
      <p class="muted small">Last question</p>
      <p class="last-q">${esc(lastQuestion.text)}</p>
      <button data-act="retry-last">Retry it</button>
    </div>` : ""}
    <p class="error" hidden></p>
  </section>`;

  $("[data-act=start]").onclick = () => startQuestion();
  $("[data-act=retry-last]")?.addEventListener("click", () => startQuestion(lastQuestion));
}

async function nextQuestion() {
  try {
    return await api(`/api/questions/next?exclude=${encodeURIComponent(state.asked.join(","))}`);
  } catch {
    state.asked = [];
    return api("/api/questions/next");
  }
}

async function startQuestion(question) {
  teardown();
  try {
    question = question || await nextQuestion();
  } catch (err) {
    return fail(`No question to ask: ${err.message}. Add some on the Questions page.`);
  }
  state.question = question;
  document.body.classList.add("focus");

  root.innerHTML = `
  <section class="focus-stage">
    <p class="focus-meta">
      <span class="lamp" aria-hidden="true"></span>
      <span class="lamp-label">Ready</span>
      <span class="muted">${esc(question.kind)}, ${question.seconds} seconds</span>
    </p>
    <h1 class="question">${esc(question.text)}</h1>
    <div class="clock">
      <div class="drain"><div class="drain-fill"></div></div>
      <span class="digits" role="timer">${mmss(question.seconds)}</span>
    </div>
    <div class="focus-controls">
      <button class="primary big" data-act="record">Record answer</button>
      <button data-act="skip">Different question</button>
      <span class="hint">Esc to leave</span>
    </div>
    <p class="error" hidden></p>
  </section>`;

  $("[data-act=record]").onclick = startRecording;
  $("[data-act=skip]").onclick = () => {
    state.asked.push(question.id);
    startQuestion();
  };
  $("[data-act=record]").focus();
}

async function startRecording() {
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    return fail(`Microphone unavailable: ${err.message}. Check the browser permission.`);
  }
  state.chunks = [];
  const recorder = new MediaRecorder(state.stream, { mimeType: "audio/webm" });
  state.recorder = recorder;
  recorder.ondataavailable = (e) => { if (e.data.size) state.chunks.push(e.data); };
  recorder.onstop = uploadAnswer;
  recorder.start();

  const limit = state.question.seconds;
  const deadline = Date.now() + limit * 1000;
  $(".lamp").classList.add("on");
  $(".lamp-label").textContent = "Recording";
  const button = $("[data-act=record]");
  button.textContent = "Stop";
  button.onclick = stopRecording;
  $("[data-act=skip]").hidden = true;

  const tick = () => {
    const left = Math.max(0, (deadline - Date.now()) / 1000);
    $(".digits").textContent = mmss(left);
    $(".clock").classList.toggle("low", left <= 15);
    $(".drain-fill").style.transform = `scaleX(${left / limit})`;
  };
  tick();
  state.ticker = setInterval(tick, 200);
  state.stopTimer = setTimeout(stopRecording, limit * 1000);
}

function stopRecording() {
  clearInterval(state.ticker);
  clearTimeout(state.stopTimer);
  if (state.recorder && state.recorder.state !== "inactive") state.recorder.stop();
  state.stream?.getTracks().forEach((t) => t.stop());
}

async function uploadAnswer() {
  renderWorking();
  const body = new FormData();
  body.append("audio", new Blob(state.chunks, { type: "audio/webm" }), "answer.webm");
  body.append("question_id", state.question.id);
  try {
    const { run_id: runId } = await api("/api/answer", { method: "POST", body });
    watchRun(runId);
  } catch (err) {
    await startQuestion(state.question);
    fail(`Upload failed: ${err.message}`);
  }
}

function renderWorking() {
  $(".focus-controls").hidden = true;
  $(".clock").hidden = true;
  $(".lamp").classList.remove("on");
  $(".lamp-label").textContent = "Working";
  $(".focus-stage").insertAdjacentHTML("beforeend",
    `<ol class="stages">${STAGES.map(([key, label]) => `<li data-stage="${key}">${label}</li>`).join("")}</ol>`);
  markStage("transcribing");
}

function markStage(stage) {
  const order = STAGES.map(([key]) => key);
  const at = order.indexOf(stage);
  root.querySelectorAll(".stages li").forEach((li) => {
    const i = order.indexOf(li.dataset.stage);
    li.classList.toggle("active", i === at);
    li.classList.toggle("passed", at > -1 && i < at);
  });
}

function watchRun(runId) {
  const source = new EventSource(`/api/runs/${runId}/events`);
  state.source = source;

  const finish = async (run) => {
    source.close();
    state.source = null;
    if (run.stage === "done") return renderFeedback(run);
    await startQuestion(state.question);
    fail(run.error || "Processing failed.");
  };

  source.onmessage = (event) => {
    const data = JSON.parse(event.data);
    markStage(data.stage);
    if (data.stage === "error") finish({ stage: "error", error: data.error });
    if (data.stage === "done") api(`/api/runs/${runId}`).then(finish);
  };

  source.onerror = () => {
    source.close();
    api(`/api/runs/${runId}`).then((run) => finish(run.stage === "done"
      ? run
      : { stage: "error", error: "Lost the progress stream. Try again." }));
  };
}

function section(tone, title, items, render) {
  if (!items?.length) return "";
  return `<section class="fb ${tone}"><h2>${title}</h2><ul>${items.map(render).join("")}</ul></section>`;
}

function renderFeedback(run) {
  document.body.classList.remove("focus");
  state.asked.push(run.question_id);
  const question = state.question;
  const fb = run.feedback || {};
  const m = run.metrics || {};
  const headline = fb.headline || fb.fixes?.[0] || "";

  root.innerHTML = `
  <article class="feedback">
    <p class="muted">${esc(question.text)}</p>
    ${headline ? `<p class="one-thing">${esc(headline)}</p>` : ""}
    ${fb.fixed_since_last?.length ? `<ul class="fixed">${fb.fixed_since_last.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` : ""}
    ${section("landed", "Landed", fb.strengths, (s) => `<li>${esc(s)}</li>`)}
    ${section("table", "Left on the table", fb.missed_points, (p) =>
      `<li>${esc(p.point)} <a class="src" href="#/stories/${encodeURIComponent(p.source_story_id)}">${esc(p.source_story_id)}</a></li>`)}
    ${section("challenged", "Would get challenged", fb.risky_claims, (r) =>
      `<li><q>${esc(r.quote)}</q><span class="why">${esc(r.why)}</span>${r.say_instead ? `<span class="say">Say instead: ${esc(r.say_instead)}</span>` : ""}</li>`)}
    <div class="strip">
      ${fb.star_coverage ? `<div class="star">${STAR.map((k) => `<span class="chip ${fb.star_coverage[k] ? "hit" : "miss"}">${k}</span>`).join("")}</div>` : ""}
      <span>${mmss(m.duration_s || 0)}${m.overran ? " (over time)" : ""}</span>
      <span>${m.words_per_minute || 0} words a minute</span>
      <span>${m.filler_count || 0} fillers</span>
      <span>longest pause ${m.longest_pause_s ? `${m.longest_pause_s}s` : "none"}</span>
    </div>
    ${fb.story_patch ? `<p class="patch-note"><a href="#/stories">1 story addition to review</a> from what you just said.</p>` : ""}
    <details class="raw"><summary>What you said</summary><p class="transcript">${esc(run.transcript?.text || "")}</p></details>
    <div class="actions">
      <button class="primary big" data-act="retry">Try again now</button>
      <button data-act="next">Next question</button>
    </div>
  </article>`;

  $("[data-act=retry]").onclick = () => startQuestion(question);
  $("[data-act=next]").onclick = () => startQuestion();
  $("[data-act=retry]").focus();
}
