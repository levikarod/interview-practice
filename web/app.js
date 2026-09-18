const $ = (sel) => document.querySelector(sel);
const show = (sel, on = true) => { $(sel).hidden = !on; };

const STATUS_LABEL = {
  stub: "stub — claim only",
  draft: "draft — needs review",
  verified: "verified",
};

const STAGE_LABEL = {
  queued: "Queued…",
  transcribing: "Transcribing locally…",
  measuring: "Measuring delivery…",
  done: "Done",
  error: "Something went wrong",
};

const state = {
  question: null,
  asked: [],
  recorder: null,
  chunks: [],
  stream: null,
  deadline: null,
  ticker: null,
  stopTimer: null,
};

const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

async function loadProfile() {
  const profile = await fetch("/api/profile").then((r) => r.json());

  if (!profile.ready) {
    $("#profile-summary").innerHTML = `<dd class="muted">${profile.reason}</dd>`;
    return;
  }

  show("#sample-banner", profile.is_example);
  show("#ingest-banner", profile.needs_ingest);
  show("#model-banner", !profile.model_cached);
  $("#model-name").textContent = profile.whisper_model;

  $("#profile-summary").innerHTML = [
    ["Name", profile.name || "—"],
    ["Roles", profile.roles],
    ["CV bullets", profile.bullets],
    ["Guardrails", profile.has_guardrails ? "set" : "none yet"],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");

  const stories = await fetch("/api/stories").then((r) => r.json());
  const { verified, draft, stub, total } = profile.stories;
  $("#story-progress").textContent =
    `${total} stories — ${verified} verified, ${draft} draft, ${stub} stub. ` +
    `Answering questions fills the empty ones in.`;

  $("#story-list").innerHTML = stories.map((s) => `
    <li class="story ${s.status}">
      <span class="badge ${s.status}">${s.status}</span>
      <span class="title">${s.title}</span>
      ${s.metric ? `<span class="metric">${s.metric}</span>` : ""}
      <span class="muted small">${STATUS_LABEL[s.status]}</span>
    </li>`).join("");
}

function panel(name) {
  for (const id of ["#idle", "#asked", "#working", "#result"]) show(id, id === name);
}

function fail(message) {
  $("#practice-error").textContent = message;
  show("#practice-error", true);
}

async function askQuestion() {
  show("#practice-error", false);
  const url = `/api/questions/next?exclude=${encodeURIComponent(state.asked.join(","))}`;
  const question = await fetch(url).then((r) => r.json());

  state.question = question;
  $("#question-text").textContent = question.text;
  $("#question-meta").textContent =
    `${question.kind} · ${question.seconds}s · ${question.tags.slice(0, 4).join(", ")}`;

  show("#record", true);
  show("#stop", false);
  show("#timer", false);
  show("#meter", false);
  show("#record-hint", false);
  panel("#asked");
}

async function startRecording() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    fail(`Microphone unavailable: ${err.message}. Check the browser permission.`);
    return;
  }

  state.stream = stream;
  state.chunks = [];
  const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
  state.recorder = recorder;

  recorder.ondataavailable = (e) => { if (e.data.size) state.chunks.push(e.data); };
  recorder.onstop = () => uploadAnswer();
  recorder.start();

  const limit = state.question.seconds;
  state.deadline = Date.now() + limit * 1000;

  show("#record", false);
  show("#stop", true);
  show("#timer", true);
  show("#meter", true);
  show("#record-hint", true);

  const tick = () => {
    const left = Math.max(0, (state.deadline - Date.now()) / 1000);
    $("#timer").textContent = mmss(left);
    $("#timer").classList.toggle("low", left <= 15);
    $("#meter-fill").style.width = `${(left / limit) * 100}%`;
  };
  tick();
  state.ticker = setInterval(tick, 200);
  state.stopTimer = setTimeout(stopRecording, limit * 1000);
}

function stopRecording() {
  clearInterval(state.ticker);
  clearTimeout(state.stopTimer);
  if (state.recorder && state.recorder.state !== "inactive") state.recorder.stop();
  if (state.stream) state.stream.getTracks().forEach((t) => t.stop());
}

async function uploadAnswer() {
  panel("#working");
  markStage("transcribing");

  const body = new FormData();
  body.append("audio", new Blob(state.chunks, { type: "audio/webm" }), "answer.webm");
  body.append("question_id", state.question.id);

  let runId;
  try {
    const res = await fetch("/api/answer", { method: "POST", body });
    if (!res.ok) throw new Error(await res.text());
    runId = (await res.json()).run_id;
  } catch (err) {
    panel("#asked");
    fail(`Upload failed: ${err.message}`);
    return;
  }

  watchRun(runId);
}

function markStage(stage) {
  $("#stage-label").textContent = STAGE_LABEL[stage] || stage;
  const order = ["transcribing", "measuring", "done"];
  const at = order.indexOf(stage);
  document.querySelectorAll(".stages li").forEach((li) => {
    const i = order.indexOf(li.dataset.stage);
    li.classList.toggle("active", i === at);
    li.classList.toggle("passed", at > -1 && i < at);
  });
}

function watchRun(runId) {
  const source = new EventSource(`/api/runs/${runId}/events`);

  source.onmessage = (event) => {
    const data = JSON.parse(event.data);
    markStage(data.stage);

    if (data.stage === "error") {
      source.close();
      panel("#asked");
      fail(data.error || "Processing failed.");
      return;
    }
    if (data.stage === "done") {
      source.close();
      fetch(`/api/runs/${runId}`).then((r) => r.json()).then(showResult);
    }
  };

  source.onerror = () => {
    source.close();
    fetch(`/api/runs/${runId}`).then((r) => r.json()).then((run) => {
      if (run.stage === "done") showResult(run);
      else { panel("#asked"); fail("Lost the progress stream. Try again."); }
    });
  };
}

function showResult(run) {
  state.asked.push(run.question_id);
  const m = run.metrics || {};

  $("#result-question").textContent = state.question.text;
  $("#transcript").textContent = run.transcript?.text || "";

  const overran = m.overran ? " over" : "";
  $("#stats").innerHTML = [
    ["Length", `${mmss(m.duration_s || 0)}${overran}`],
    ["Pace", `${m.words_per_minute || 0} wpm`],
    ["Fillers", m.filler_count || 0],
    ["Longest pause", m.longest_pause_s ? `${m.longest_pause_s}s` : "—"],
  ].map(([k, v]) => `<div class="stat"><span class="k">${k}</span><span class="v">${v}</span></div>`)
   .join("");

  panel("#result");
}

$("#start").onclick = askQuestion;
$("#skip").onclick = askQuestion;
$("#again").onclick = askQuestion;
$("#record").onclick = startRecording;
$("#stop").onclick = stopRecording;

loadProfile().catch((err) => {
  $("#profile-summary").innerHTML = `<dd class="muted">Failed to load: ${err.message}</dd>`;
});
