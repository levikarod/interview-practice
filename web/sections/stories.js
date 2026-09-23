import { api, esc, json } from "../lib.js";

const STATUSES = [
  ["stub", "Stubs", "A claim from your CV with no detail yet. Answering questions fills these in."],
  ["draft", "Drafts", "Detail from your answers, waiting for you to check it."],
  ["verified", "Verified", "Wording and facts you've confirmed."],
];
const SECTIONS = ["situation", "task", "action", "result", "reflection"];
const LABEL = {
  claim: "Claim", situation: "Situation", task: "Task",
  action: "Action", result: "Result", reflection: "Reflection",
};

let root;

export async function mount(el, params) {
  root = el;
  return params[0] ? renderStory(params[0]) : renderList();
}

async function renderList() {
  const [stories, additions] = await Promise.all([api("/api/stories"), api("/api/story-additions")]);
  const count = (status) => stories.filter((s) => s.status === status).length;

  root.innerHTML = `
  <section class="page">
    <h1 class="page-title">Stories</h1>
    ${stories.length ? `
    <div class="progress" role="img" aria-label="${count("verified")} verified, ${count("draft")} draft, ${count("stub")} stub">
      ${[...STATUSES].reverse().map(([status]) => `<span class="bar ${status}" style="flex-grow:${count(status)}"></span>`).join("")}
    </div>
    <p class="muted">${stories.length} stories: ${count("verified")} verified, ${count("draft")} draft, ${count("stub")} stub.</p>`
    : `<p class="lede">No stories yet. <a href="#/profile">Upload your CV</a> and each achievement on it becomes one.</p>`}
    ${additions.length ? `
    <section class="review">
      <h2>To review</h2>
      <p class="muted small">Suggested from your answers, in your own words. Tick the parts to keep.</p>
      ${additions.map(renderAddition).join("")}
    </section>` : ""}
    ${STATUSES.map(([status, title, hint]) => {
      const rows = stories.filter((s) => s.status === status);
      if (!rows.length) return "";
      return `
      <section class="group">
        <h2>${title}</h2>
        <p class="muted small">${hint}</p>
        <ul class="story-list">${rows.map((s) => `
          <li><a href="#/stories/${encodeURIComponent(s.id)}">${esc(s.title)}</a>${s.metric ? `<span class="metric">${esc(s.metric)}</span>` : ""}</li>`).join("")}
        </ul>
      </section>`;
    }).join("")}
  </section>`;

  root.querySelectorAll(".addition").forEach(bindAddition);
}

function renderAddition(addition) {
  const patch = addition.patch;
  const current = addition.story || {};
  const rows = SECTIONS.filter((k) => (patch[k] || "").trim());
  return `
  <article class="addition" data-run="${esc(addition.run_id)}">
    <h3>${addition.story ? esc(addition.story.title) : `New story: ${esc(patch.story_id)}`}</h3>
    ${rows.map((k) => `
    <label class="diff">
      <input type="checkbox" name="${k}" checked>
      <span class="diff-label">${LABEL[k]}</span>
      ${current[k] ? `<span class="was">${esc(current[k])}</span>` : ""}
      <span class="now">${esc(patch[k])}</span>
    </label>`).join("")}
    <div class="actions">
      <button class="primary" data-act="accept">Accept selected</button>
      <button data-act="dismiss">Dismiss</button>
    </div>
    <p class="error" hidden></p>
  </article>`;
}

function bindAddition(card) {
  const path = `/api/story-additions/${encodeURIComponent(card.dataset.run)}`;
  const fail = (err) => {
    const box = card.querySelector(".error");
    box.textContent = err.message;
    box.hidden = false;
  };
  card.querySelector("[data-act=accept]").onclick = () => {
    const sections = [...card.querySelectorAll("input:checked")].map((box) => box.name);
    api(`${path}/accept`, json("POST", { sections })).then(renderList, fail);
  };
  card.querySelector("[data-act=dismiss]").onclick = () =>
    api(`${path}/dismiss`, { method: "POST" }).then(renderList, fail);
}

async function renderStory(id) {
  let story;
  try {
    story = await api(`/api/stories/${encodeURIComponent(id)}`);
  } catch {
    root.innerHTML = `<section class="page"><p><a href="#/stories">All stories</a></p><p>There's no story called ${esc(id)}.</p></section>`;
    return;
  }

  root.innerHTML = `
  <article class="page">
    <p><a href="#/stories">All stories</a></p>
    <h1 class="page-title">${esc(story.title)}</h1>
    <p class="story-meta">
      <span class="badge ${esc(story.status)}">${esc(story.status)}</span>
      ${story.role ? `<span>${esc(story.role)}</span>` : ""}
      ${story.metric ? `<span class="metric">${esc(story.metric)}</span>` : ""}
      ${story.verified ? `<span class="muted">verified ${esc(story.verified)}</span>` : ""}
    </p>
    ${["claim", ...SECTIONS].map((k) => `
    <section class="story-part">
      <h2>${LABEL[k]}</h2>
      ${story[k] ? `<p>${esc(story[k])}</p>` : `<p class="muted">Not told yet.</p>`}
    </section>`).join("")}
    ${story.status === "draft" ? `<div class="actions"><button class="primary" data-act="verify">Mark verified</button></div>` : ""}
    <p class="error" hidden></p>
  </article>`;

  root.querySelector("[data-act=verify]")?.addEventListener("click", () =>
    api(`/api/stories/${encodeURIComponent(id)}/verify`, { method: "POST" })
      .then(() => renderStory(id), (err) => {
        const box = root.querySelector(".error");
        box.textContent = err.message;
        box.hidden = false;
      }));
}
