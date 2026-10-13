const BASE = "http://127.0.0.1:8765";
const SPIN = ["[=     ]","[ =    ]","[  =   ]","[   =  ]","[    = ]","[     =]","[    = ]","[   =  ]","[  =   ]","[ =    ]"];
const $ = (id) => document.getElementById(id);
let token = "", es = null, busy = false, spinI = 0, live = null, retry = 0;

function line(text, cls) {
  const d = document.createElement("div"); d.className = "line " + (cls || ""); d.textContent = text;
  $("log").appendChild(d); $("log").scrollTop = 1e9; return d;
}
function setBusy(b, label) {
  busy = b; $("state").textContent = label || (b ? "working" : "READY");
  $("stop").disabled = $("take").disabled = !b; $("msg").disabled = false;
}
setInterval(() => { if (busy) { spinI = (spinI + 1) % SPIN.length; $("spin").textContent = SPIN[spinI];
  $("state").textContent = $("state").textContent.replace(/\.*$/, "") + ".".repeat(spinI % 4); } else $("spin").textContent = ""; }, 120);

async function post(path, body) {
  const r = await fetch(BASE + path, {method: "POST", headers: {"Content-Type": "application/json", "X-PCA-Token": token}, body: JSON.stringify(body || {})});
  if (r.status === 401) { showSetup("Token rejected."); throw new Error("bad token"); }
  return r.json();
}
async function highlight(x, y) {
  try { const [tab] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
        if (tab) chrome.tabs.sendMessage(tab.id, {type: "pca-highlight", x, y}).catch(() => {}); } catch (e) {}
}
function onEvent(ev) {
  const m = JSON.parse(ev.data);
  switch (m.type) {
    case "hello": retry = 0; $("conn").textContent = "[connected]"; setBusy(m.busy); refreshStatus(); break;
    case "status": setBusy(m.state !== "ready", m.state === "ready" ? "READY" : m.state); if (m.state === "ready") live = null; break;
    case "token": if (!live) live = line("", "bot"); live.textContent += m.text; $("log").scrollTop = 1e9; break;
    case "chat": if (live) { live.textContent = m.text; live = null; } else line(m.text, "bot"); break;
    case "task": line("task: " + m.text, "warn"); break;
    case "step": { const d = line("", "step"); d.innerHTML = ""; const b = document.createElement("b");
      b.textContent = `[${m.n}] ${m.action}`; d.appendChild(b); d.append(" " + (m.detail || "")); break; }
    case "log": if (!/^Abort:|^Run folder:/.test(m.text)) line(m.text, "step"); break;
    case "highlight": if (m.x != null) highlight(m.x, m.y); break;
    case "confirm": showConfirm(m); break;
    case "confirm_done": { const c = document.querySelector(`[data-cid="${m.id}"]`);
      if (c) { c.querySelectorAll("button").forEach(b => b.remove()); c.append(m.ok ? "  -> ALLOWED" : "  -> DENIED"); } break; }
    case "result": line("result: " + m.text, "bot"); break;
    case "stopped": case "takeover": line(m.text, "warn"); break;
    case "error": line("error: " + m.text, "err"); break;
  }
}
function showConfirm(m) {
  const box = document.createElement("div"); box.className = "confirm"; box.dataset.cid = m.id;
  box.textContent = "!! CONFIRM ACTION !!\n" + m.message + "\n";
  for (const [txt, ok] of [["[ Y ] ALLOW", true], ["[ N ] DENY", false]]) {
    const b = document.createElement("button"); b.textContent = txt; b.onclick = () => post("/confirm", {id: m.id, ok}); box.appendChild(b);
  }
  $("log").appendChild(box); $("log").scrollTop = 1e9;
}
function connect() {
  if (es) es.close();
  es = new EventSource(`${BASE}/events?token=${encodeURIComponent(token)}`);
  es.onmessage = onEvent;
  es.onerror = () => { $("conn").textContent = "[offline - is Liscia Agent open?]"; es.close();
    fetch(`${BASE}/health`, {headers: {"X-PCA-Token": token}}).then(r => { if (r.status === 401) showSetup("Token rejected."); }).catch(() => {});
    setTimeout(connect, Math.min(1000 * 2 ** retry++, 15000)); };
}
function showSetup(msg) { $("setup").hidden = false; if (msg) line(msg, "err"); }
$("save").onclick = async () => { token = $("tok").value.trim(); await chrome.storage.local.set({token}); $("setup").hidden = true; connect(); };  // the service worker picks the token up from storage too
$("stop").onclick = () => post("/stop");
$("take").onclick = () => post("/takeover");
$("f").onsubmit = async (e) => {
  e.preventDefault(); const text = $("msg").value.trim(); if (!text) return;
  $("msg").value = ""; line(text, "user");
  try { const r = await post("/chat", {text}); if (!r.accepted) line("busy - press STOP first, or wait.", "warn"); }
  catch (err) { line("can't reach Liscia Agent: " + err.message, "err"); }
};
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && busy) post("/stop"); });
chrome.storage.local.get("token").then(({token: t}) => {
  line("Liscia Agent side panel. Chat, or tell it to do things in the browser. Esc / STOP to halt.", "dim");
  if (t) { token = t; connect(); } else showSetup();
});

async function refreshStatus() {
  try {
    const r = await fetch(`${BASE}/status`, {headers: {"X-PCA-Token": token}}); if (!r.ok) return;
    const st = await r.json(), on = st.extension && st.extension.connected;
    $("conn").textContent = on ? "[connected · page control ON]" : "[connected · page control OFF - reload the extension]";
  } catch (e) {}
}
setInterval(() => { if (token && es && es.readyState === 1) refreshStatus(); }, 10000);
