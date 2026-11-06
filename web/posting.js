import { api, json } from "./lib.js";

const PROMPT = "PDF, Markdown or text, or paste it below.";

export const POSTING_SOURCE = `
  <div class="actions jd-source">
    <button type="button" data-posting="choose">Upload the posting</button>
    <span class="muted small" data-posting="name">${PROMPT}</span>
    <button type="button" data-posting="clear" hidden>Use pasted text instead</button>
    <input type="file" data-posting="file" accept=".pdf,.md,.txt" hidden>
  </div>
  <textarea data-posting="text" rows="7" placeholder="Paste the full posting. Responsibilities and requirements are where the questions come from."></textarea>`;

export function postingSource(scope) {
  const part = (name) => scope.querySelector(`[data-posting=${name}]`);
  const choose = (file) => {
    part("name").textContent = file ? file.name : PROMPT;
    part("text").disabled = Boolean(file);
    part("clear").hidden = !file;
  };
  part("choose").onclick = () => part("file").click();
  part("file").onchange = () => choose(part("file").files[0]);
  part("clear").onclick = () => { part("file").value = ""; choose(null); };

  return {
    draft() {
      const body = new FormData();
      const file = part("file").files[0];
      if (file) body.append("file", file);
      else body.append("text", part("text").value.trim());
      return api("/api/jd/generate", { method: "POST", body });
    },
    reset() {
      part("text").value = "";
      part("file").value = "";
      choose(null);
    },
  };
}

export const keepPosting = (drafted, questions, title = drafted.title) =>
  api("/api/jds", json("POST", {
    title, role_summary: drafted.role_summary, text: drafted.text, questions,
  }));
