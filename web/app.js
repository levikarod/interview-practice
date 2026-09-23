import { api, esc } from "./lib.js";
import * as practice from "./sections/practice.js";
import * as questions from "./sections/questions.js";
import * as stories from "./sections/stories.js";
import * as profile from "./sections/profile.js";

const SECTIONS = { practice, questions, stories, profile };
const view = document.getElementById("view");
let current = null;

function parse() {
  const [name, ...params] = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  return { name: SECTIONS[name] ? name : "practice", params: params.map(decodeURIComponent) };
}

function refreshRail() {
  api("/api/profile").then((p) => {
    const badge = document.querySelector('[data-section="stories"] .count');
    badge.textContent = p.pending_additions || "";
    badge.hidden = !p.pending_additions;
  }).catch(console.error);
}

async function route() {
  const { name, params } = parse();
  current?.unmount?.();
  document.body.classList.remove("focus");
  document.querySelectorAll(".rail [data-section]").forEach((a) => {
    if (a.dataset.section === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  view.replaceChildren();
  current = SECTIONS[name];
  refreshRail();
  try {
    await current.mount(view, params);
  } catch (err) {
    view.innerHTML = `<p class="error">Couldn't load this section: ${esc(err.message)}</p>`;
  }
}

async function start() {
  if (!location.hash) {
    const p = await api("/api/profile").catch(() => ({ ready: false }));
    if (!p.ready || p.is_example || p.needs_ingest) history.replaceState(null, "", "#/profile");
  }
  addEventListener("hashchange", route);
  route();
}

start();
