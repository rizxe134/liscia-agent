// Liscia Agent service worker: long-polls the local bridge for commands and carries them out in Chrome.
const BASE = "http://127.0.0.1:8765";
const VERSION = chrome.runtime.getManifest().version;
chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true}).catch(() => {});

let running = false, backoff = 1000;
async function token() { return (await chrome.storage.local.get("token")).token || ""; }
async function api(path, body, signal) {
  const t = await token(); if (!t) throw new Error("no token");
  const r = await fetch(BASE + path, {method: body ? "POST" : "GET", signal,
    headers: {"X-PCA-Token": t, "Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
  if (r.status === 401) throw new Error("token rejected");
  return r.json();
}
async function loop() {
  if (running) return; running = true;
  try {
    while (true) {
      let cmds;
      try {
        const data = await api(`/ext/poll?hold=20&version=${VERSION}&client=sw`);
        cmds = data.commands || []; backoff = 1000;
      } catch (e) { await new Promise(r => setTimeout(r, backoff)); backoff = Math.min(backoff * 2, 15000); continue; }
      for (const c of cmds) handle(c);  // run concurrently; each posts its own result
    }
  } finally { running = false; }
}
async function handle(c) {
  let out;
  try { out = {id: c.id, ok: true, result: await run(c.cmd, c.args || {})}; }
  catch (e) { out = {id: c.id, ok: false, error: String(e && e.message || e)}; }
  try { await api("/ext/result", out); } catch (e) {}
}

async function activeTab() {
  const [t] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
  if (!t) throw new Error("no active tab"); return t;
}
function restricted(url) { return !url || /^(chrome|edge|about|chrome-extension|devtools|view-source):/.test(url) || url.startsWith("https://chromewebstore.google.com"); }
async function inPage(tabId, fn, args = []) {
  const call = async () => (await chrome.scripting.executeScript({target: {tabId}, world: "ISOLATED",
    func: async (fn, args) => { if (!window.__liscia) return {__missing: true};
      try { return {v: await window.__liscia[fn](...args)}; } catch (e) { return {__err: String(e.message || e)}; } }, args: [fn, args]}))[0].result;
  let r = await call();
  if (r && r.__missing) { await chrome.scripting.executeScript({target: {tabId}, files: ["content.js"]}); r = await call(); }
  if (!r) throw new Error("page did not respond");
  if (r.__err) throw new Error(r.__err);
  return r.v;
}
function waitLoaded(tabId, ms = 10000) {
  return new Promise((resolve) => {
    const done = () => { chrome.tabs.onUpdated.removeListener(l); clearTimeout(t); resolve(); };
    const l = (id, info) => { if (id === tabId && info.status === "complete") done(); };
    const t = setTimeout(done, ms); chrome.tabs.onUpdated.addListener(l);
    chrome.tabs.get(tabId).then(tab => { if (tab.status === "complete") done(); }).catch(done);
  });
}
async function trustedClick(tabId, x, y) {  // fallback: real (isTrusted) mouse events via the debugger protocol
  const target = {tabId};
  await chrome.debugger.attach(target, "1.3");
  try {
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"])
      await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {type, x, y, button: "left", clickCount: type === "mouseMoved" ? 0 : 1});
  } finally { await chrome.debugger.detach(target).catch(() => {}); }
}
async function trustedKey(tabId, key) {
  const target = {tabId}, vk = {Enter: 13, Tab: 9, Escape: 27, Backspace: 8, ArrowDown: 40, ArrowUp: 38}[key] || 0;
  await chrome.debugger.attach(target, "1.3");
  try {
    await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {type: "rawKeyDown", key, windowsVirtualKeyCode: vk, text: key === "Enter" ? "\r" : undefined});
    await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {type: "keyUp", key, windowsVirtualKeyCode: vk});
  } finally { await chrome.debugger.detach(target).catch(() => {}); }
}

async function run(cmd, a) {
  if (cmd === "ping") return {pong: true, version: VERSION};
  if (cmd === "tabs") return (await chrome.tabs.query({})).map(t => ({id: t.id, index: t.index, title: t.title, url: t.url, active: t.active, windowId: t.windowId}));
  if (cmd === "navigate" || cmd === "new_tab") {
    let url = String(a.url || ""); if (!/^[a-z]+:/i.test(url)) url = "https://" + url;
    if (!/^https?:/i.test(url)) throw new Error("only http(s) URLs");
    const tab = cmd === "new_tab" ? await chrome.tabs.create({url, active: true}) : await chrome.tabs.update((await activeTab()).id, {url});
    await waitLoaded(tab.id); const t = await chrome.tabs.get(tab.id); return {url: t.url, title: t.title, tabId: t.id};
  }
  if (cmd === "back") { const t = await activeTab(); await chrome.tabs.goBack(t.id); await waitLoaded(t.id, 6000); return {ok: true}; }
  if (cmd === "switch_tab") {
    const tabs = await chrome.tabs.query({lastFocusedWindow: true});
    const t = a.tabId ? tabs.find(x => x.id === a.tabId) : a.index != null ? tabs.find(x => x.index === Number(a.index)) :
      tabs.find(x => (x.title + " " + x.url).toLowerCase().includes(String(a.match || "").toLowerCase()));
    if (!t) throw new Error("no such tab"); await chrome.tabs.update(t.id, {active: true}); return {title: t.title, url: t.url};
  }
  if (cmd === "close_tab") { const t = a.tabId ? {id: a.tabId} : await activeTab(); await chrome.tabs.remove(t.id); return {closed: t.id}; }
  if (cmd === "screenshot") { const t = await activeTab(); return {dataUrl: await chrome.tabs.captureVisibleTab(t.windowId, {format: "jpeg", quality: 60}), url: t.url}; }

  const tab = await activeTab();
  if (restricted(tab.url)) throw new Error(`can't access ${tab.url || "this tab"} (browser page) - navigate to a website first`);
  switch (cmd) {
    case "snapshot": { const s = await inPage(tab.id, "snapshot", [a]); s.tabId = tab.id; return s; }
    case "click": {
      const p = await inPage(tab.id, "prepare", [a.id]);
      if (a.trusted) { await trustedClick(tab.id, p.x, p.y); return {clicked: p.label, trusted: true}; }
      try { return await inPage(tab.id, "click", [a.id]); }
      catch (e) { await trustedClick(tab.id, p.x, p.y); return {clicked: p.label, trusted: true, note: String(e.message || e)}; }
    }
    case "type": await inPage(tab.id, "prepare", [a.id]); return await inPage(tab.id, "type", [a.id, String(a.text || ""), {press_enter: !!a.press_enter, clear: a.clear}]);
    case "press": if (a.trusted) { await trustedKey(tab.id, a.key || "Enter"); return {pressed: a.key, trusted: true}; }
                  return await inPage(tab.id, "press", [a.key || "Enter", a.id || null]);
    case "select": await inPage(tab.id, "prepare", [a.id]); return await inPage(tab.id, "select", [a.id, a.value]);
    case "hover": await inPage(tab.id, "prepare", [a.id]); return await inPage(tab.id, "hover", [a.id]);
    case "scroll": return await inPage(tab.id, "scroll", [a]);
    case "wait_for": return await inPage(tab.id, "wait_for", [a]);
    case "extract_text": return await inPage(tab.id, "extract_text", [a]);
    case "first_video": return await inPage(tab.id, "first_video", []);
  }
  throw new Error("unknown command " + cmd);
}

// page events from content scripts -> agent
chrome.runtime.onMessage.addListener((m, sender) => {
  if (m && m.type === "page_event" && sender.tab && sender.tab.active) api("/ext/event", {...m, tabId: sender.tab.id}).catch(() => {});
});
chrome.tabs.onActivated.addListener(async ({tabId}) => {
  try { const t = await chrome.tabs.get(tabId); api("/ext/event", {kind: "tab_switched", url: t.url, title: t.title, tabId}).catch(() => {}); } catch (e) {}
});
// keep the poll loop alive: restart on wake-ups and every 30 s via alarms
chrome.alarms.create("liscia-keepalive", {periodInMinutes: 0.5});
chrome.alarms.onAlarm.addListener(() => loop());
chrome.runtime.onStartup.addListener(() => loop());
chrome.runtime.onInstalled.addListener(() => loop());
chrome.storage.onChanged.addListener((c) => { if (c.token) loop(); });
loop();
