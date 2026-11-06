import { api, esc, json } from "../lib.js";
import { POSTING_SOURCE, keepPosting, postingSource } from "../posting.js";

let root;
let state;
const $ = (sel) => root.querySelector(sel);
const $$ = (sel) => [...root.querySelectorAll(sel)];
const show = (sel, on = true) => { $(sel).hidden = !on; };

const TEMPLATE = `
<section class="page">
  <h1 class="page-title">Questions</h1>
  <p class="lede">The bank practice draws from. Add your own, turn off ones you don't need, or draft new ones from a job posting.</p>

  <section class="group">
    <h2>From a job description</h2>
    <p class="muted small">Questions are drafted where the role's requirements overlap your own material, plus a couple aimed at gaps worth rehearsing honestly. Nothing is saved until you pick, and the ones you keep stay together so you can practise just that role.</p>
    ${POSTING_SOURCE}
    <div class="actions">
      <button id="generate" class="primary">Draft questions</button>
      <span class="muted small" id="jd-status"></span>
    </div>
    <div id="drafted" hidden>
      <label class="jd-title">Name this set<input id="jd-title" type="text" maxlength="80"></label>
      <p class="role-summary" id="role-summary"></p>
      <div class="actions">
        <button id="select-all">Select all</button>
        <button id="select-none">Select none</button>
        <button id="keep" class="primary">Add selected</button>
      </div>
      <ul class="drafts" id="drafts"></ul>
    </div>
    <p id="jd-error" class="error" hidden></p>
  </section>

  <section class="group">
    <h2>Your bank</h2>
    <div class="actions">
      <select id="jd-filter" aria-label="Which questions"><option value="">All questions</option></select>
      <button id="jd-practise" class="primary" hidden>Practise these</button>
      <input id="filter" type="search" placeholder="Filter by text or tag">
      <label class="toggle"><input type="checkbox" id="show-disabled"> show turned off</label>
      <button id="add-new">Add your own</button>
      <span class="muted small" id="bank-count"></span>
    </div>
    <p id="bank-error" class="error" hidden></p>
    <ul class="qlist" id="qlist"></ul>
  </section>
</section>

<dialog id="editor">
  <form method="dialog" id="edit-form">
    <h3 id="edit-title">Edit question</h3>
    <label>Question<textarea name="text" rows="3" required></textarea></label>
    <div class="row">
      <label>Kind
        <select name="kind">
          <option value="technical">technical</option>
          <option value="behavioural">behavioural</option>
          <option value="system-design">system-design</option>
        </select>
      </label>
      <label>Seconds<input name="seconds" type="number" min="30" max="600" step="10"></label>
    </div>
    <label>Tags <span class="muted small">comma separated. These decide which of your stories gets found.</span>
      <input name="tags" type="text">
    </label>
    <p id="edit-error" class="error" hidden></p>
    <div class="actions">
      <button value="cancel">Cancel</button>
      <button value="save" class="primary">Save question</button>
    </div>
  </form>
</dialog>`;

export async function mount(el) {
  root = el;
  state = { bank: [], jds: [], drafts: [], posting: null, editing: null };
  root.innerHTML = TEMPLATE;
  bind();
  try {
    await loadBank();
  } catch (err) {
    $("#qlist").innerHTML = `<li class="muted">Couldn't load the bank: ${esc(err.message)}</li>`;
  }
}

function toQuestion(row) {
  const { is_core, ...question } = row;
  return question;
}

const tagList = (tags) => (tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("");

const jdTitle = (id) => {
  const posting = state.jds.find((j) => j.id === id);
  return posting ? posting.title || posting.id : id;
};

async function loadBank(select) {
  [state.bank, state.jds] = await Promise.all([
    api(`/api/questions?include_disabled=${$("#show-disabled").checked}`),
    api("/api/jds"),
  ]);
  const picker = $("#jd-filter");
  const keep = select ?? picker.value;
  picker.innerHTML = `<option value="">All questions</option>` + state.jds.map((j) =>
    `<option value="${esc(j.id)}">${esc(j.title || j.id)} (${j.questions})</option>`).join("");
  picker.value = state.jds.some((j) => j.id === keep) ? keep : "";
  renderBank();
}

function renderBank() {
  const needle = $("#filter").value.trim().toLowerCase();
  const posting = $("#jd-filter").value;
  const rows = state.bank.filter((q) =>
    (!posting || q.jd_id === posting) && (
      !needle ||
      q.text.toLowerCase().includes(needle) ||
      (q.tags || []).some((t) => t.toLowerCase().includes(needle))));

  show("#jd-practise", Boolean(posting));
  $("#bank-count").textContent = `${rows.length} of ${state.bank.length} shown`;
  $("#qlist").innerHTML = rows.map((q) => `
    <li class="qrow ${q.enabled ? "" : "off"}" data-id="${esc(q.id)}">
      <div class="qmain">
        <p class="qtext">${esc(q.text)}</p>
        <p class="qmeta">
          <span class="badge ${esc(q.source)}">${esc(q.source)}</span>
          <span class="muted small">${esc(q.kind)}, ${q.seconds}s</span>
          ${q.jd_id ? `<span class="target">for ${esc(jdTitle(q.jd_id))}</span>` : ""}
          ${tagList(q.tags)}
        </p>
        ${q.note ? `<p class="qnote">${esc(q.note)}</p>` : ""}
      </div>
      <div class="qactions">
        <button data-act="edit">Edit</button>
        <button data-act="delete">${q.enabled ? "Turn off" : "Turn on"}</button>
      </div>
    </li>`).join("") || `<li class="muted">Nothing matches.</li>`;
}

function openEditor(question) {
  state.editing = question ?? {
    id: "", text: "", tags: [], seconds: 120, kind: "technical",
    enabled: true, source: "custom", note: "",
  };
  const form = $("#edit-form");
  $("#edit-title").textContent = question ? "Edit question" : "Add a question";
  form.text.value = state.editing.text;
  form.kind.value = state.editing.kind;
  form.seconds.value = state.editing.seconds;
  form.tags.value = (state.editing.tags || []).join(", ");
  show("#edit-error", false);
  $("#editor").showModal();
}

function renderDrafts() {
  $("#drafts").innerHTML = state.drafts.map((q, i) => `
    <li class="draft">
      <label>
        <input type="checkbox" data-i="${i}" checked>
        <span class="qtext">${esc(q.text)}</span>
      </label>
      <p class="qmeta">
        <span class="muted small">${esc(q.kind)}, ${q.seconds}s</span>
        ${q.targets_story_id ? `<span class="target">for ${esc(q.targets_story_id)}</span>` : ""}
        ${tagList(q.tags)}
      </p>
      ${q.note ? `<p class="qnote">${esc(q.note)}</p>` : ""}
    </li>`).join("");
}

const setAll = (checked) => $$("#drafts input[type=checkbox]").forEach((box) => { box.checked = checked; });

function bind() {
  $("#qlist").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const id = button.closest(".qrow").dataset.id;
    const question = state.bank.find((q) => q.id === id);
    if (button.dataset.act === "edit") return openEditor(question);

    const path = `/api/questions/${encodeURIComponent(id)}`;
    show("#bank-error", false);
    try {
      if (question.enabled) await api(path, { method: "DELETE" });
      else await api(path, json("PUT", { ...toQuestion(question), enabled: true }));
      loadBank();
    } catch (err) {
      $("#bank-error").textContent = err.message;
      show("#bank-error", true);
    }
  });

  $("#edit-form").addEventListener("submit", async (event) => {
    if (event.submitter?.value !== "save") return;
    event.preventDefault();
    const form = $("#edit-form");
    const body = {
      ...toQuestion(state.editing),
      text: form.text.value.trim(),
      kind: form.kind.value,
      seconds: Number(form.seconds.value) || 120,
      tags: form.tags.value.split(",").map((t) => t.trim()).filter(Boolean),
    };
    if (!body.text) {
      $("#edit-error").textContent = "A question needs some text.";
      return show("#edit-error", true);
    }
    try {
      if (state.editing.id) {
        await api(`/api/questions/${encodeURIComponent(state.editing.id)}`, json("PUT", body));
      } else {
        await api("/api/questions", json("POST", body));
      }
      $("#editor").close();
      loadBank();
    } catch (err) {
      $("#edit-error").textContent = err.message;
      show("#edit-error", true);
    }
  });

  const source = postingSource(root);

  $("#generate").onclick = async () => {
    show("#jd-error", false);
    show("#drafted", false);
    $("#generate").disabled = true;
    $("#jd-status").textContent = "Reading the posting against your material…";
    try {
      const result = await source.draft();
      state.drafts = result.questions;
      state.posting = result;
      $("#jd-title").value = result.title;
      $("#role-summary").textContent = result.role_summary;
      $("#jd-status").textContent = `${result.questions.length} drafted, $${result.cost_usd}`;
      renderDrafts();
      show("#drafted", true);
    } catch (err) {
      $("#jd-status").textContent = "";
      $("#jd-error").textContent = err.message;
      show("#jd-error", true);
    } finally {
      $("#generate").disabled = false;
    }
  };

  $("#select-all").onclick = () => setAll(true);
  $("#select-none").onclick = () => setAll(false);

  $("#keep").onclick = async () => {
    const chosen = $$("#drafts input[type=checkbox]:checked").map((box) => state.drafts[Number(box.dataset.i)]);
    if (!chosen.length) {
      $("#jd-status").textContent = "Nothing selected.";
      return;
    }
    let saved;
    try {
      saved = await keepPosting(state.posting, chosen, $("#jd-title").value.trim());
    } catch (err) {
      $("#jd-error").textContent = err.message;
      return show("#jd-error", true);
    }
    $("#jd-status").innerHTML = `Kept ${saved.added} for ${esc(saved.title || "this posting")}. <a href="#/practice/jd/${encodeURIComponent(saved.id)}">Practise them now</a>`;
    show("#drafted", false);
    source.reset();
    loadBank(saved.id);
  };

  $("#jd-filter").onchange = renderBank;
  $("#jd-practise").onclick = () => {
    location.hash = `#/practice/jd/${encodeURIComponent($("#jd-filter").value)}`;
  };
  $("#filter").oninput = renderBank;
  $("#show-disabled").onchange = () => loadBank();
  $("#add-new").onclick = () => openEditor(null);
}
