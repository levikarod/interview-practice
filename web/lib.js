export const esc = (value) => String(value ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const mmss = (s) =>
  `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export const json = (method, data) => ({ method, body: JSON.stringify(data) });

function describeError(body) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
  }
  return null;
}

export async function api(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const res = await fetch(path, {
    ...options,
    headers: isForm ? undefined : { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const error = new Error(describeError(body) || `${res.status} ${res.statusText}`);
    error.status = res.status;
    throw error;
  }
  return res.json();
}
