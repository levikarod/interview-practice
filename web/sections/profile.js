import { api, esc, json } from "../lib.js";

let root;
const $ = (sel) => root.querySelector(sel);

function showError(message) {
  const box = $(".error");
  box.textContent = message;
  box.hidden = false;
}

const hideError = () => { $(".error").hidden = true; };

export async function mount(el) {
  root = el;
  const profile = await api("/api/profile");
  if (!profile.ready || profile.is_example) return renderUpload(profile);
  if (profile.needs_ingest) return renderReview((await api("/api/cv")).markdown);
  return renderReady(profile);
}

function renderUpload(profile) {
  const replacing = profile.ready && !profile.is_example;
  root.innerHTML = `
  <section class="page">
    <h1 class="page-title">${replacing ? "Upload a new CV" : "Start with your CV"}</h1>
    <p class="lede">Your CV becomes a story bank, one entry per achievement. Feedback then tells you which of them you could have used and didn't.</p>
    <div class="drop">
      <p class="drop-title">Drop your CV here</p>
      <button class="primary" data-act="choose">Choose a file</button>
      <p class="muted small">PDF, Markdown or plain text. The file stays on this computer; its text is sent to Claude once to convert it.</p>
      <input type="file" accept=".pdf,.md,.txt" hidden>
    </div>
    <p class="notice working" hidden>Converting your CV. This takes about half a minute.</p>
    <div class="confirm" hidden>
      <p>You already have a CV here. Replacing it keeps every story you've filled in.</p>
      <div class="actions">
        <button class="primary" data-act="replace">Replace it</button>
        <button data-act="cancel">Keep the current one</button>
      </div>
    </div>
    ${profile.is_example ? `<p class="muted small">Until then you can <a href="#/practice">practise on sample data</a>.</p>` : ""}
    <p class="error" hidden></p>
  </section>`;

  const input = $("input[type=file]");
  const drop = $(".drop");
  $("[data-act=choose]").onclick = () => input.click();
  input.onchange = () => input.files[0] && send(input.files[0], false);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    const file = e.dataTransfer.files[0];
    if (file) send(file, false);
  };
}

async function send(file, replace) {
  const body = new FormData();
  body.append("file", file);
  body.append("replace", replace ? "true" : "false");
  hideError();
  $(".drop").hidden = true;
  $(".working").hidden = false;
  try {
    const { markdown } = await api("/api/cv", { method: "POST", body });
    renderReview(markdown);
  } catch (err) {
    $(".working").hidden = true;
    if (err.status === 409) {
      $(".confirm").hidden = false;
      $("[data-act=replace]").onclick = () => { $(".confirm").hidden = true; send(file, true); };
      $("[data-act=cancel]").onclick = () => mount(root);
      return;
    }
    $(".drop").hidden = false;
    showError(err.message);
  }
}

function renderReview(markdown) {
  root.innerHTML = `
  <section class="page wide">
    <h1 class="page-title">Check your CV</h1>
    <p class="lede">This is what was read from your file. Check each role's title and employer: those lines are the ones most often misread, and every bullet under them becomes a story.</p>
    <textarea class="cv-text" spellcheck="false" aria-label="Your CV">${esc(markdown)}</textarea>
    <div class="actions">
      <button class="primary" data-act="build">Build story bank</button>
      <span class="muted small working" hidden>Building…</span>
    </div>
    <p class="error" hidden></p>
  </section>`;

  $("[data-act=build]").onclick = async () => {
    hideError();
    $(".working").hidden = false;
    try {
      await api("/api/cv", json("PUT", { markdown: $(".cv-text").value }));
      const built = await api("/api/cv/build", { method: "POST" });
      renderReady(await api("/api/profile"), built);
    } catch (err) {
      $(".working").hidden = true;
      showError(err.message);
    }
  };
}

function renderReady(profile, built) {
  root.innerHTML = `
  <section class="page">
    <h1 class="page-title">${esc(profile.name || "Your profile")}</h1>
    ${profile.headline ? `<p class="lede">${esc(profile.headline)}</p>` : ""}
    ${built ? `<p class="notice">Story bank built: ${built.stubs_created} new stories, ${built.stories_kept} kept as they were. <a href="#/practice">Start practising</a>.</p>` : ""}
    <dl class="tally">
      <div><dt>Roles</dt><dd>${profile.roles}</dd></div>
      <div><dt>CV bullets</dt><dd>${profile.bullets}</dd></div>
      <div><dt>Stories</dt><dd>${profile.stories.total}</dd></div>
    </dl>
    <div class="actions">
      <button data-act="edit">Edit CV</button>
      <button data-act="upload">Upload a new CV</button>
    </div>
    ${profile.unsourced_metrics.length ? `
    <section class="group">
      <h2>Numbers to defend</h2>
      <p class="muted small">Figures on your CV with nothing written behind them. Expect to be asked how you measured each one.</p>
      <ul class="defend">${profile.unsourced_metrics.map(([metric, text]) => `
        <li><strong>${esc(metric)}</strong><span class="muted small">${esc(text)}</span></li>`).join("")}
      </ul>
    </section>` : ""}
    <section class="group">
      <h2>Guardrails</h2>
      <p class="muted small">Claims you know you can't defend, or figures that are out of date. Feedback marks your answer red when you make one of them.</p>
      <textarea class="guardrails" rows="8" aria-label="Guardrails"></textarea>
      <div class="actions">
        <button data-act="save-guardrails">Save guardrails</button>
        <span class="muted small saved" hidden>Saved</span>
      </div>
    </section>
    <p class="error" hidden></p>
  </section>`;

  api("/api/guardrails").then((g) => { $(".guardrails").value = g.markdown; });
  $("[data-act=edit]").onclick = async () => renderReview((await api("/api/cv")).markdown);
  $("[data-act=upload]").onclick = () => renderUpload(profile);
  $("[data-act=save-guardrails]").onclick = async () => {
    hideError();
    try {
      await api("/api/guardrails", json("PUT", { markdown: $(".guardrails").value }));
      $(".saved").hidden = false;
    } catch (err) {
      showError(err.message);
    }
  };
}
