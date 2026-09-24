// ── API layer: every path resolves against the SITE ROOT (host reverse-proxies
//    /api/* to this user's own workspace dashboard). NOT document.baseURI — the
//    page lives under /app/v2/ and APIs live at /api/*. ────────────────────────
export const apiUrl = path => new URL(String(path).replace(/^\/+/, ""), location.origin + "/").toString();

const j = r => { if (!r.ok) throw new Error("http " + r.status); return r.json(); };

export const getState  = () => fetch(apiUrl("api/state")).then(j);
export const getMe     = () => fetch(apiUrl("api/me")).then(j);

// per-version base:  api/study/<sid>[ /version/<v> ]
export const base = (sid, ver) =>
  apiUrl("api/study/" + encodeURIComponent(sid) + (ver ? "/version/" + encodeURIComponent(ver) : ""));

export const getDetail   = (sid, ver) => fetch(base(sid, ver)).then(j);
export const getAgents   = (sid, ver) => fetch(base(sid, ver) + "/agents").then(j);
export const getAgent    = (sid, aid, ver) => fetch(base(sid, ver) + "/agent/" + encodeURIComponent(aid)).then(j);
export const getFiles    = (sid, ver) => fetch(base(sid, ver) + "/files").then(j);
export const getTables   = (sid, ver) => fetch(base(sid, ver) + "/data/tables").then(j);
export const getTableRows= (sid, name, limit, offset, ver) =>
  fetch(base(sid, ver) + "/data/table/" + encodeURIComponent(name) + `?limit=${limit}&offset=${offset}`).then(j);
export const getPaper    = (sid, ver) => fetch(base(sid, ver) + "/paper").then(j);
export const getLiterature = (sid, ver) => fetch(base(sid, ver) + "/literature").then(j);

export const figureUrl = (sid, ver, name) => base(sid, ver) + "/figure/" + encodeURIComponent(name);
export const fileUrl   = (sid, ver, rel)  => base(sid, ver) + "/file/" + rel.split("/").map(encodeURIComponent).join("/");
export const tableCsvUrl = (sid, name) => base(sid, null) + "/data/table/" + encodeURIComponent(name) + ".csv";
export const exportUrl = (sid, fmt) => apiUrl(`api/studies/${encodeURIComponent(sid)}/export?fmt=${fmt}`);
export const paperExportUrl = (sid, fmt) => apiUrl(`api/studies/${encodeURIComponent(sid)}/paper-export?fmt=${fmt}`);

// chat plane (host endpoints; feature-detected via ping)
export const chatPing   = () => fetch(apiUrl("api/chat/ping")).then(j);
export const chatSend   = (sid, message) =>
  fetch(apiUrl(`api/chat/${encodeURIComponent(sid)}`), {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({message})});
export const chatStopReq= sid => fetch(apiUrl(`api/chat/${encodeURIComponent(sid)}/stop`), {method:"POST"});
export const chatAnswer = (sid, gate_id, answers) =>
  fetch(apiUrl(`api/chat/${encodeURIComponent(sid)}/answer`), {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({gate_id, answers})});
export const chatUpload = (sid, file) => {
  const fd = new FormData(); fd.append("file", file);
  return fetch(apiUrl(`api/chat/${encodeURIComponent(sid)}/upload`), {method:"POST", body:fd}).then(j);
};
export const chatFetchUrl = (sid, url) =>
  fetch(apiUrl(`api/chat/${encodeURIComponent(sid)}/fetch-url`), {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({url})}).then(j);
export const chatStream = sid => new EventSource(apiUrl(`api/chat/${encodeURIComponent(sid)}/stream`));
export const obsStream  = () => new EventSource(apiUrl("api/stream"));
