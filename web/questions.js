const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const show = (sel, on = true) => { $(sel).hidden = !on; };
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const state = { bank: [], drafts: [], editing: null };

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(describeError(body) || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

function describeError(body) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`)
      .join("; ");
  }
  return null;
}

function toQuestion(row) {
  const { is_core, ...question } = row;
  return question;
}

function tagList(tags) {
  return (tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("");
}

async function loadBank() {
  const showDisabled = $("#show-disabled").checked;
  state.bank = await api(`/api/questions?include_disabled=${showDisabled}`);
  renderBank();
}

function renderBank() {
  const needle = $("#filter").value.trim().toLowerCase();
  const rows = state.bank.filter((q) =>
    !needle ||
    q.text.toLowerCase().includes(needle) ||
    (q.tags || []).some((t) => t.toLowerCase().includes(needle))
  );

  $("#bank-count").textContent =
    `${rows.length} of ${state.bank.length} shown`;

  $("#qlist").innerHTML = rows.map((q) => `
    <li class="qrow ${q.enabled ? "" : "off"}" data-id="${esc(q.id)}">
      <div class="qmain">
        <p class="qtext">${esc(q.text)}</p>
        <p class="qmeta">
          <span class="badge ${q.source}">${esc(q.source)}</span>
          <span class="muted small">${esc(q.kind)} · ${q.seconds}s</span>
          ${tagList(q.tags)}
        </p>
        ${q.note ? `<p class="qnote">${esc(q.note)}</p>` : ""}
      </div>
      <div class="qactions">
        <button class="ghost" data-act="edit">Edit</button>
        <button class="ghost" data-act="delete">${q.enabled ? "Remove" : "Restore"}</button>
      </div>
    </li>`).join("") || `<li class="muted">Nothing matches.</li>`;
}

$("#qlist").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-act]");
  if (!button) return;
  const id = button.closest(".qrow").dataset.id;
  const question = state.bank.find((q) => q.id === id);

  if (button.dataset.act === "edit") return openEditor(question);

  if (question.enabled) {
    await api(`/api/questions/${encodeURIComponent(id)}`, { method: "DELETE" });
  } else {
    await api(`/api/questions/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify({ ...toQuestion(question), enabled: true }),
    });
  }
  loadBank();
});

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
      await api(`/api/questions/${encodeURIComponent(state.editing.id)}`,
        { method: "PUT", body: JSON.stringify(body) });
    } else {
      await api("/api/questions", { method: "POST", body: JSON.stringify(body) });
    }
    $("#editor").close();
    loadBank();
  } catch (err) {
    $("#edit-error").textContent = err.message;
    show("#edit-error", true);
  }
});

$("#generate").onclick = async () => {
  const text = $("#jd").value.trim();
  show("#jd-error", false);
  show("#drafted", false);
  $("#generate").disabled = true;
  $("#jd-status").textContent = "Reading the posting against your material…";

  try {
    const result = await api("/api/jd/generate", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    state.drafts = result.questions;
    $("#role-summary").textContent = result.role_summary;
    $("#jd-status").textContent =
      `${result.questions.length} drafted · $${result.cost_usd}`;
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

function renderDrafts() {
  $("#drafts").innerHTML = state.drafts.map((q, i) => `
    <li class="draft">
      <label>
        <input type="checkbox" data-i="${i}" checked>
        <span class="qtext">${esc(q.text)}</span>
      </label>
      <p class="qmeta">
        <span class="muted small">${esc(q.kind)} · ${q.seconds}s</span>
        ${q.targets_story_id
          ? `<span class="target">→ ${esc(q.targets_story_id)}</span>` : ""}
        ${tagList(q.tags)}
      </p>
      ${q.note ? `<p class="qnote">${esc(q.note)}</p>` : ""}
    </li>`).join("");
}

const setAll = (checked) =>
  $$("#drafts input[type=checkbox]").forEach((box) => { box.checked = checked; });

$("#select-all").onclick = () => setAll(true);
$("#select-none").onclick = () => setAll(false);

$("#keep").onclick = async () => {
  const chosen = $$("#drafts input[type=checkbox]:checked")
    .map((box) => state.drafts[Number(box.dataset.i)]);

  if (!chosen.length) {
    $("#jd-status").textContent = "Nothing selected.";
    return;
  }

  await api("/api/questions/bulk", {
    method: "POST",
    body: JSON.stringify(chosen),
  });
  $("#jd-status").textContent = `Added ${chosen.length} to your bank.`;
  show("#drafted", false);
  $("#jd").value = "";
  loadBank();
};

$("#filter").oninput = renderBank;
$("#show-disabled").onchange = loadBank;
$("#add-new").onclick = () => openEditor(null);

loadBank().catch((err) => {
  $("#qlist").innerHTML = `<li class="muted">Failed to load: ${esc(err.message)}</li>`;
});
