const $ = (sel) => document.querySelector(sel);

const STATUS_LABEL = {
  stub: "stub — claim only",
  draft: "draft — needs review",
  verified: "verified",
};

async function load() {
  const profile = await fetch("/api/profile").then((r) => r.json());

  if (!profile.ready) {
    $("#profile-summary").innerHTML =
      `<dd class="muted">${profile.reason}</dd>`;
    return;
  }

  $("#sample-banner").hidden = !profile.is_example;
  $("#ingest-banner").hidden = !profile.needs_ingest;

  const rows = [
    ["Name", profile.name || "—"],
    ["Roles", profile.roles],
    ["CV bullets", profile.bullets],
    ["Guardrails", profile.has_guardrails ? "set" : "none yet"],
  ];
  $("#profile-summary").innerHTML = rows
    .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
    .join("");

  const stories = await fetch("/api/stories").then((r) => r.json());
  const { verified, draft, stub, total } = profile.stories;

  $("#story-progress").textContent =
    `${total} stories — ${verified} verified, ${draft} draft, ${stub} stub. ` +
    `Answering questions fills the empty ones in.`;

  $("#story-list").innerHTML = stories
    .map(
      (s) => `
      <li class="story ${s.status}">
        <span class="badge ${s.status}">${s.status}</span>
        <span class="title">${s.title}</span>
        ${s.metric ? `<span class="metric">${s.metric}</span>` : ""}
        <span class="muted small">${STATUS_LABEL[s.status]}</span>
      </li>`
    )
    .join("");
}

load().catch((err) => {
  $("#profile-summary").innerHTML =
    `<dd class="muted">Failed to load: ${err.message}</dd>`;
});
