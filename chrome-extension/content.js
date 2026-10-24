// Liscia Agent content script: page snapshots + DOM actions, driven by the service worker.
(() => {
if (window.__liscia) return;  // injected twice (manifest + on-demand) -> keep the first
const L = window.__liscia = {};
const SEL = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[role=tab],' +
  '[role=menuitem],[role=option],[role=checkbox],[role=radio],[role=switch],[role=combobox],[role=searchbox],[role=textbox],' +
  '[contenteditable=""],[contenteditable=true],[onclick],[tabindex]:not([tabindex="-1"])';
let nextId = 1;

function visible(e, below = 0) {  // below = how many extra screens under the fold still count
  const r = e.getBoundingClientRect();
  if (r.width < 3 || r.height < 3 || r.bottom < 0 || r.right < 0 || r.top > innerHeight * (1 + below) || r.left > innerWidth) return false;
  const st = getComputedStyle(e);
  return st.visibility !== "hidden" && st.display !== "none" && parseFloat(st.opacity || "1") > 0.05;
}
function label(e) {
  const by = e.getAttribute("aria-labelledby");
  let t = by ? by.split(/\s+/).map(i => (document.getElementById(i) || {}).innerText || "").join(" ") : "";
  t = t || e.getAttribute("aria-label") || e.getAttribute("title") || e.getAttribute("alt") || "";
  if (!t && e.id) { const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l) t = l.innerText; }
  if (!t) t = e.innerText || e.value || e.getAttribute("placeholder") || "";
  if (!t) { const im = e.querySelector && e.querySelector("img[alt]"); if (im) t = im.alt; }
  return t.replace(/\s+/g, " ").trim().slice(0, 100);
}
function role(e) {
  const r = e.getAttribute("role"); if (r) return r;
  const t = e.tagName.toLowerCase();
  if (t === "a") return "link"; if (t === "button" || t === "summary") return "button";
  if (t === "select") return "select"; if (t === "textarea") return "textbox";
  if (t === "input") { const ty = (e.type || "text").toLowerCase();
    return ({checkbox: "checkbox", radio: "radio", submit: "button", button: "button", search: "searchbox", range: "slider"})[ty] || "textbox"; }
  if (e.isContentEditable) return "textbox";
  return t;
}
function idOf(e) {
  let id = e.getAttribute("data-liscia-id");
  if (!id) { id = String(nextId++); e.setAttribute("data-liscia-id", id); }
  return id;
}
function dialogs() {
  return [...document.querySelectorAll('dialog[open],[role=dialog],[role=alertdialog],[aria-modal=true]')].filter(visible)
    .map(d => ({label: label(d).slice(0, 80) || (d.innerText || "").replace(/\s+/g, " ").trim().slice(0, 80)}));
}
function summary(max = 1200) {
  const parts = [];
  document.querySelectorAll("h1,h2,h3,[role=heading]").forEach(h => { if (visible(h) && parts.length < 12) parts.push("# " + h.innerText.replace(/\s+/g, " ").trim().slice(0, 90)); });
  const body = (document.body && document.body.innerText || "").replace(/\s+/g, " ").trim();
  return (parts.join("\n") + "\n" + body).slice(0, max);
}
const YT_RESULTS = 'ytd-video-renderer a#video-title,ytd-rich-item-renderer a#video-title-link,ytd-playlist-renderer a,ytd-channel-renderer a#main-link';
L.snapshot = (opts = {}) => {
  // on-screen elements first, then elements up to `below` screens under the fold (marked below:true; clicking scrolls to them)
  const max = opts.max || 110, below = opts.below != null ? opts.below : 3, out = [], seen = new Set();
  const onScreen = [], offScreen = [];
  for (const e of document.querySelectorAll(SEL)) {
    if (e.closest("[aria-hidden=true]") || e.closest("#" + HOST_ID) || !visible(e, below)) continue;
    (e.getBoundingClientRect().top > innerHeight ? offScreen : onScreen).push(e);
  }
  // YouTube: video titles are the most important off-screen elements
  const yt = new Set(location.hostname.includes("youtube.") ? [...document.querySelectorAll(YT_RESULTS)] : []);
  offScreen.sort((a, b) => (yt.has(b) ? 1 : 0) - (yt.has(a) ? 1 : 0));
  for (const e of onScreen.concat(offScreen)) {
    if (out.length >= max) break;
    const r = e.getBoundingClientRect(), text = label(e);
    const key = text + "|" + Math.round(r.left / 8) + "|" + Math.round(r.top / 8);
    if (seen.has(key)) continue; seen.add(key);
    const el = {id: idOf(e), role: role(e), label: text, tag: e.tagName.toLowerCase(),
      bbox: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]};
    if ("value" in e && e.value && el.role !== "button") el.value = String(e.value).slice(0, 80);
    if (e.href) el.href = e.href.slice(0, 160);
    if (e.tagName === "INPUT") { el.itype = (e.type || "text").toLowerCase(); if (e.name) el.name = e.name.slice(0, 40);
      if (e.autocomplete) el.autocomplete = e.autocomplete.slice(0, 40); if (e.placeholder) el.placeholder = e.placeholder.slice(0, 60); }
    if (e.disabled) el.disabled = true;
    if (e.checked) el.checked = true;
    if (document.activeElement === e) el.focused = true;
    if (r.top > innerHeight) el.below = true;
    out.push(el);
  }
  return {url: location.href, title: document.title, elements: out, dialogs: dialogs(), text: summary(opts.text || 1200),
    scroll: [Math.round(scrollY), Math.round(document.documentElement.scrollHeight - innerHeight)],
    viewport: [innerWidth, innerHeight], ready: document.readyState, status: httpStatus()};
};
function find(id) {
  const e = document.querySelector(`[data-liscia-id="${CSS.escape(String(id))}"]`);
  if (!e) throw new Error(`element ${id} not found (page changed? take a new snapshot)`);
  return e;
}
function flash(e) {
  const r = e.getBoundingClientRect(), b = document.createElement("div"), s = b.style;
  Object.assign(s, {position: "fixed", zIndex: 2147483647, pointerEvents: "none", left: r.left - 3 + "px", top: r.top - 3 + "px",
    width: r.width + "px", height: r.height + "px", border: "3px solid #00ff66", boxShadow: "0 0 18px #00ff66", borderRadius: "6px", transition: "opacity .4s"});
  const tag = document.createElement("div"); tag.textContent = "Liscia Agent";
  Object.assign(tag.style, {position: "absolute", top: "-20px", left: "0", background: "#000", color: "#00ff66", font: "11px Menlo,monospace", padding: "1px 5px", border: "1px solid #00ff66"});
  b.appendChild(tag); document.documentElement.appendChild(b);
  setTimeout(() => { s.opacity = "0"; setTimeout(() => b.remove(), 450); }, 1200);
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
// 2.2.0: visible agent cursor + "agent is using this tab" banner. Closed shadow DOM on <html> (not <body>), pointer-events:none
// except the Stop button, so page styles can't touch it and snapshots / find / elementFromPoint never see it.
const VIZ = {on: false, cursor: true, banner: true, host: null, root: null, x: innerWidth / 2, y: innerHeight / 2};
const HOST_ID = "liscia-agent-overlay-host";
function vizHost() {
  if (VIZ.host && VIZ.host.isConnected) return VIZ.root;
  const h = document.createElement("liscia-agent-overlay"); h.id = HOST_ID; h.setAttribute("aria-hidden", "true");
  h.style.cssText = "all:initial;position:fixed;inset:0;z-index:2147483647;pointer-events:none;display:block";
  const r = h.attachShadow({mode: "closed"});
  const st = document.createElement("style"); st.textContent = `:host{all:initial}
    #cur{position:fixed;left:0;top:0;width:26px;height:26px;transform:translate(-100px,-100px);transition:transform .45s cubic-bezier(.22,.8,.3,1);
         filter:drop-shadow(0 2px 3px rgba(0,0,0,.45));display:none}
    #lab{position:fixed;left:0;top:0;transform:translate(-200px,-200px);transition:transform .45s cubic-bezier(.22,.8,.3,1);font:600 12px/1.2 -apple-system,Segoe UI,sans-serif;
         background:#111;color:#3dff8f;padding:3px 7px;border-radius:6px;border:1px solid #3dff8f;white-space:nowrap;display:none}
    #box{position:fixed;border:2px solid #3dff8f;border-radius:6px;box-shadow:0 0 0 4px rgba(61,255,143,.25);display:none;transition:all .25s}
    .rip{position:fixed;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;border:3px solid #3dff8f;animation:rip .6s ease-out forwards}
    @keyframes rip{to{transform:scale(3.4);opacity:0}}
    #ban{position:fixed;top:6px;left:50%;transform:translateX(-50%);display:none;align-items:center;gap:10px;background:rgba(17,17,17,.92);color:#fff;
         font:600 12px/1 -apple-system,Segoe UI,sans-serif;padding:6px 8px 6px 12px;border-radius:999px;border:1px solid #3dff8f;box-shadow:0 2px 10px rgba(0,0,0,.35);transition:opacity .2s}
    #ban .dot{color:#3dff8f;animation:pulse 1.2s infinite}@keyframes pulse{50%{opacity:.3}}
    #stop{pointer-events:auto;cursor:pointer;background:#ff4d5e;color:#fff;border:0;border-radius:999px;padding:4px 10px;font:700 11px -apple-system,Segoe UI,sans-serif}`; r.appendChild(st);  // no innerHTML: works under Trusted Types
  const mk = (tag, id, ns) => { const e = ns ? document.createElementNS(ns, tag) : document.createElement(tag); if (id) e.id = id; r.appendChild(e); return e; };
  mk("div", "box");
  const SVG = "http://www.w3.org/2000/svg", svg = mk("svg", "cur", SVG); svg.setAttribute("viewBox", "0 0 24 24");
  const path = document.createElementNS(SVG, "path"); path.setAttribute("d", "M3 2l7.5 19 2.6-7.9L21 10.5z");
  for (const [k, v] of [["fill", "#3dff8f"], ["stroke", "#0b0b0b"], ["stroke-width", "1.6"], ["stroke-linejoin", "round"]]) path.setAttribute(k, v);
  svg.appendChild(path); mk("div", "lab");
  const ban = mk("div", "ban"), dot = document.createElement("span"), txt = document.createElement("span"), stop = document.createElement("button");
  dot.className = "dot"; dot.textContent = "\u25cf"; txt.textContent = "Liscia Agent is using this tab"; stop.id = "stop"; stop.textContent = "Stop";
  ban.append(dot, txt, stop);
  r.getElementById("stop").addEventListener("click", (ev) => { ev.stopPropagation(); try { chrome.runtime.sendMessage({type: "agent_stop"}); } catch (e) {} vizOff(); });
  document.documentElement.appendChild(h); VIZ.host = h; VIZ.root = r; return r;
}
function vizOff() { VIZ.on = false; if (VIZ.host) VIZ.host.remove(); VIZ.host = VIZ.root = null; }
L.viz = async (o = {}) => {
  if (o.on === false) { vizOff(); return {on: false}; }
  VIZ.on = true; VIZ.cursor = o.cursor !== false; VIZ.banner = o.banner !== false;
  const r = vizHost(); r.getElementById("ban").style.display = VIZ.banner ? "flex" : "none";
  return {on: true};
};
function isOverlay(n) { return !!n && (n === VIZ.host || (n.id === HOST_ID)); }
async function cursorTo(e, text) {
  if (!VIZ.on || !VIZ.cursor || !e) return;
  const r = vizHost(), rc = e.getBoundingClientRect(), x = rc.left + rc.width / 2, y = rc.top + rc.height / 2;
  const cur = r.getElementById("cur"), lab = r.getElementById("lab"), box = r.getElementById("box"), ban = r.getElementById("ban");
  cur.style.display = lab.style.display = "block";
  Object.assign(box.style, {display: "block", left: rc.left - 3 + "px", top: rc.top - 3 + "px", width: rc.width + 2 + "px", height: rc.height + 2 + "px"});
  cur.style.transform = `translate(${x - 3}px,${y - 2}px)`; lab.textContent = (text || "").slice(0, 60);
  lab.style.transform = `translate(${Math.min(x + 18, innerWidth - 220)}px,${y + 18}px)`;
  const br = ban.getBoundingClientRect();  // never let the banner sit over the target (trusted clicks hit-test the real screen)
  ban.style.opacity = (rc.top < br.bottom + 4 && rc.right > br.left && rc.left < br.right) ? "0" : "1";
  VIZ.x = x; VIZ.y = y; await sleep(480);
}
function ripple(x, y) {
  if (!VIZ.on || !VIZ.cursor) return;
  const r = vizHost(), d = document.createElement("div"); d.className = "rip"; d.style.left = x + "px"; d.style.top = y + "px";
  r.appendChild(d); setTimeout(() => d.remove(), 700);
  setTimeout(() => { const b = r.getElementById("box"); if (b) b.style.display = "none"; const ban = r.getElementById("ban"); if (ban) ban.style.opacity = "1"; }, 900);
}

function center(e) { const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }
function mouse(e, type, x, y) {
  const o = {bubbles: true, cancelable: true, composed: true, view: window, clientX: x, clientY: y, button: 0, buttons: type.endsWith("down") ? 1 : 0};
  e.dispatchEvent(type.startsWith("pointer") ? new PointerEvent(type, {...o, pointerId: 1, pointerType: "mouse", isPrimary: true}) : new MouseEvent(type, o));
}
L.prepare = async (id, verb) => {  // scroll into view + highlight; returns viewport centre for a trusted click fallback
  const e = find(id); e.scrollIntoView({block: "center", inline: "center"}); await sleep(120);
  if (VIZ.on && VIZ.cursor) await cursorTo(e, `${verb || "clicking"} ${label(e).slice(0, 40)}`.trim()); else { flash(e); await sleep(350); }
  const [x, y] = center(e); return {x, y, label: label(e)};
};
const CLICKABLE = 'a[href],button,input,select,textarea,label,summary,[role=button],[role=link],[role=tab],[role=menuitem],[role=option],[onclick]';
function activate(t, x, y) {
  // SVG icons and other non-HTMLElement targets have no .click(): use the closest clickable ancestor, else a synthetic click event
  const c = (t && t.closest && t.closest(CLICKABLE)) || t;
  if (c && typeof c.click === "function") { c.click(); return; }
  (t || document.body).dispatchEvent(new MouseEvent("click", {bubbles: true, cancelable: true, composed: true, view: window, clientX: x, clientY: y, button: 0}));
}
function httpStatus() {
  try { const n = performance.getEntriesByType("navigation")[0]; return n && n.responseStatus ? n.responseStatus : null; } catch (e) { return null; }
}
L.click = async (id) => {
  const e = find(id), [x, y] = center(e);
  let target = document.elementFromPoint(x, y) || e;
  if (isOverlay(target)) target = e;  // our own overlay never counts as "covering" the element
  const hit = (target === e || e.contains(target)) ? target : e;
  ripple(x, y);
  for (const t of ["pointerover", "mouseover", "pointerdown", "mousedown"]) mouse(hit, t, x, y);
  if (e.focus) e.focus({preventScroll: true});
  for (const t of ["pointerup", "mouseup"]) mouse(hit, t, x, y);
  activate(hit, x, y);
  return {clicked: label(e), covered: hit !== target};
};
function setValue(e, v) {
  const proto = e.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : e.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  const desc = Object.getOwnPropertyDescriptor(proto, "value");
  desc && desc.set ? desc.set.call(e, v) : (e.value = v);
}
function key(e, k, type) {
  const codes = {Enter: 13, Tab: 9, Escape: 27, Backspace: 8, ArrowDown: 40, ArrowUp: 38, ArrowLeft: 37, ArrowRight: 39, " ": 32};
  e.dispatchEvent(new KeyboardEvent(type, {key: k, code: k.length === 1 ? "Key" + k.toUpperCase() : k, keyCode: codes[k] || k.charCodeAt(0),
    which: codes[k] || k.charCodeAt(0), bubbles: true, cancelable: true, composed: true}));
}
L.press = async (k, id) => {
  const e = id ? find(id) : (document.activeElement || document.body);
  key(e, k, "keydown"); key(e, k, "keypress");
  if (k === "Enter" && e.form && (e.tagName === "INPUT")) {
    const btn = e.form.querySelector("[type=submit],button:not([type])");
    if (e.form.requestSubmit) e.form.requestSubmit(btn || undefined); else e.form.submit();
  }
  key(e, k, "keyup");
  return {pressed: k};
};
L.type = async (id, text, opts = {}) => {
  const e = find(id); e.focus();
  if (e.isContentEditable) {
    if (opts.clear !== false) { document.execCommand("selectAll"); document.execCommand("delete"); }
    document.execCommand("insertText", false, text);
  } else {
    setValue(e, opts.clear === false ? (e.value || "") + text : text);
    e.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: text}));
    e.dispatchEvent(new Event("change", {bubbles: true}));
  }
  if (opts.press_enter) { await sleep(80); await L.press("Enter", id); }
  return {typed: text.length};
};
L.select = async (id, value) => {
  const e = find(id);
  if (e.tagName !== "SELECT") throw new Error("element is not a <select>");
  const o = [...e.options].find(o => o.value === value || o.text.trim().toLowerCase() === String(value).toLowerCase());
  if (!o) throw new Error(`no option '${value}'`);
  setValue(e, o.value); e.dispatchEvent(new Event("input", {bubbles: true})); e.dispatchEvent(new Event("change", {bubbles: true}));
  return {selected: o.text};
};
L.hover = async (id) => { const e = find(id), [x, y] = center(e); for (const t of ["pointerover", "pointerenter", "mouseover", "mouseenter", "mousemove"]) mouse(e, t, x, y); return {hovered: label(e)}; };
L.scroll = async (args = {}) => {
  if (VIZ.on && VIZ.cursor) { const r = vizHost(), lab = r.getElementById("lab"), cur = r.getElementById("cur");
    cur.style.display = lab.style.display = "block"; cur.style.transform = `translate(${innerWidth - 60}px,${innerHeight / 2}px)`;
    lab.textContent = "scrolling " + (args.direction || "down"); lab.style.transform = `translate(${innerWidth - 200}px,${innerHeight / 2 + 22}px)`; }
  if (args.id) { find(args.id).scrollIntoView({block: "center"}); return {scrolled: "to element"}; }
  const h0 = document.documentElement.scrollHeight, y0 = scrollY;
  const dy = args.amount != null ? Number(args.amount) : (args.direction === "up" ? -0.8 : 0.8) * innerHeight;
  window.scrollBy({top: dy, behavior: "instant"}); await sleep(250);
  if (dy > 0 && args.wait_lazy !== false) {  // wait for lazy-loaded results (YouTube continuation etc.)
    const end = Date.now() + Math.min(args.wait_ms || 2500, 6000);
    while (Date.now() < end && document.documentElement.scrollHeight === h0 && innerHeight + scrollY >= h0 - 50) await sleep(200);
  }
  const h = document.documentElement.scrollHeight;
  return {scrollY: Math.round(scrollY), moved: Math.round(scrollY - y0), grew: h > h0, at_bottom: innerHeight + scrollY >= h - 4};
};
function words(s) { return String(s || "").toLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N} ]+/gu, " ").split(/\s+/).filter(Boolean); }
L.find_text = async (args = {}) => {
  // best element (whole page, not only the viewport) whose label contains the words of args.text; scrolls it into view
  const want = words(args.text); if (!want.length) throw new Error("find_text needs text");
  const pool = [...(location.hostname.includes("youtube.") ? document.querySelectorAll(YT_RESULTS) : []), ...document.querySelectorAll(SEL)];
  let best = null, bestScore = 0;
  for (const e of pool) {
    if (e.closest("[aria-hidden=true],ytd-ad-slot-renderer,ytd-in-feed-ad-layout-renderer,#masthead,ytd-searchbox")) continue;
    const r = e.getBoundingClientRect(); if (r.width < 3 || r.height < 3) continue;
    if (["INPUT", "TEXTAREA"].includes(e.tagName)) continue;
    const have = words(label(e)); if (!have.length) continue;
    const hit = want.filter(w => have.some(h => h.startsWith(w))).length / want.length;
    const score = hit + (e.href && e.href.includes("/watch") ? 0.05 : 0);
    if (hit >= (args.min || 0.99) && score > bestScore) { best = e; bestScore = score; }
  }
  if (!best) return {found: false};
  const id = idOf(best); if (args.reveal !== false) { best.scrollIntoView({block: "center"}); await sleep(150); flash(best); }
  return {found: true, id, label: label(best), href: best.href || null};
};
L.extract_text = (args = {}) => args.id ? {text: (find(args.id).innerText || "").slice(0, args.max || 4000)} : {text: summary(args.max || 4000)};
L.wait_for = async (args = {}) => {
  const end = Date.now() + Math.min(args.timeout_ms || 8000, 20000);
  while (Date.now() < end) {
    if (args.selector && document.querySelector(args.selector)) return {found: args.selector};
    if (args.text && (document.body.innerText || "").toLowerCase().includes(String(args.text).toLowerCase())) return {found: args.text};
    if (!args.selector && !args.text && document.readyState === "complete") return {found: "load"};
    await sleep(250);
  }
  throw new Error("timed out waiting for " + (args.text || args.selector || "page load"));
};
L.first_video = async () => {
  const sels = ['ytd-video-renderer a#video-title', 'ytd-rich-item-renderer a#video-title-link', 'a#video-title-link', 'a#video-title',
                'ytd-video-renderer a#thumbnail', 'ytd-rich-item-renderer a#thumbnail', 'a[href^="/watch"]'];
  for (const s of sels) for (const e of document.querySelectorAll(s)) {
    if (visible(e, 6) && e.href && e.href.includes("/watch") && !e.closest("ytd-ad-slot-renderer,ytd-in-feed-ad-layout-renderer")) {
      const id = idOf(e); await L.prepare(id); await L.click(id); return {clicked: label(e), href: e.href};
    }
  }
  throw new Error("no video link on this page");
};

// 2.0.1: every YouTube result with its title, channel and kind (video / mix / playlist / short), for best-match picking
L.video_results = async (args) => {
  const out = [], seen = new Set();
  const rows = document.querySelectorAll("ytd-video-renderer,ytd-radio-renderer,ytd-playlist-renderer,ytd-rich-item-renderer,ytd-compact-video-renderer,yt-lockup-view-model,ytd-reel-item-renderer");
  for (const r of rows) {
    if (r.closest("ytd-ad-slot-renderer,ytd-in-feed-ad-layout-renderer,ytd-promoted-video-renderer")) continue;
    // 2.1.1: the TITLE link, not the thumbnail (whose text is "2:05 Now playing")
    const a = r.querySelector("a#video-title,a#video-title-link,a.yt-lockup-metadata-view-model-wiz__title,a[class*='lockup-metadata'][href],h3 a[href]") ||
              r.querySelector("a[href*='/watch'],a[href*='/shorts/']");
    if (!a || !a.href || seen.has(a.href)) continue; seen.add(a.href);
    const h = r.querySelector("#video-title,h3,[class*='lockup-metadata'] [role='heading']");
    const title = (a.getAttribute("title") || (h && h.textContent) || a.getAttribute("aria-label") || a.innerText || "").replace(/\s+/g, " ").trim();
    const ch = r.querySelector("ytd-channel-name a, #channel-name a, .yt-content-metadata-view-model-wiz__metadata-text");
    const tag = r.tagName.toLowerCase();
    const kind = /radio/.test(tag) || /[?&]start_radio=1/.test(a.href) || /^mix\b/i.test(title) ? "mix" : /playlist/.test(tag) || /[?&]list=/.test(a.href) ? "playlist" : /\/shorts\//.test(a.href) || /reel/.test(tag) ? "short" : "video";
    out.push({id: idOf(a), title: title.slice(0, 160), channel: ch ? ch.innerText.trim().slice(0, 60) : "", href: a.href.slice(0, 200), kind});
    if (out.length >= (args && args.limit || 25)) break;
  }
  return {url: location.href, results: out};
};
L.media_state = async () => {
  const v = document.querySelector("video");
  const t = (document.querySelector("h1.ytd-watch-metadata yt-formatted-string, #title h1, h1.title") || {}).innerText || document.title.replace(/ - YouTube$/, "");
  const ch = (document.querySelector("ytd-watch-metadata ytd-channel-name a, #owner #channel-name a") || {}).innerText || "";
  return {url: location.href, title: (t || "").trim(), channel: ch.trim(), has_video: !!v, paused: v ? v.paused : null, time: v ? v.currentTime : null,
          ad: adShowing(), skippable: !!skipButton()};
};
L.media_control = async (args) => {
  const v = document.querySelector("video"); if (!v) throw new Error("no video on this page");
  if (args.op === "pause") v.pause(); else if (args.op === "play") await v.play().catch(() => {});
  return {paused: v.paused};
};

// 2.1.1: auto ad-skip. Click "Skip"/"Skip Ad" as soon as it shows, close overlay/banner ads, mute unskippable ads (optional).
const SKIP_SEL = ".ytp-skip-ad-button,.ytp-ad-skip-button,.ytp-ad-skip-button-modern,.ytp-ad-skip-button-slot button,.ytp-ad-skip-button-container button," +
                 "button[id^='skip-button'],.videoAdUiSkipButton";
const CLOSE_SEL = ".ytp-ad-overlay-close-button,.ytp-ad-overlay-close-container button,ytd-banner-promo-renderer #dismiss-button button," +
                  "ytd-statement-banner-renderer #dismiss-button button,.ytp-featured-product-close-button";
function adShowing() { const p = document.querySelector("#movie_player,.html5-video-player"); return !!(p && (p.classList.contains("ad-showing") || p.classList.contains("ad-interrupting"))); }
function visible(e) { if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== "hidden"; }
function skipButton() {
  const b = [...document.querySelectorAll(SKIP_SEL)].find(visible);
  if (b) return b;
  return [...document.querySelectorAll(".html5-video-player button")].find(x => visible(x) && /^\s*skip(\s+ads?)?\s*$/i.test(x.innerText || x.getAttribute("aria-label") || ""));
}
const AD = {on: false, mute: true, skipped: 0, closed: 0, muted_by_us: false, timer: null};
function adTick() {
  const v = document.querySelector("video"), b = skipButton();
  if (b) { b.click(); AD.skipped++; }
  for (const c of document.querySelectorAll(CLOSE_SEL)) if (visible(c)) { c.click(); AD.closed++; }
  const ad = adShowing();
  if (v && AD.mute && ad && !v.muted) { v.muted = true; AD.muted_by_us = true; }
  if (v && !ad && AD.muted_by_us) { v.muted = false; AD.muted_by_us = false; }
}
L.ad_watch = async (args = {}) => {
  AD.mute = args.mute !== false;
  if (args.on === false) { AD.on = false; clearInterval(AD.timer); AD.timer = null; adTick(); return {on: false, skipped: AD.skipped}; }
  if (!AD.timer) AD.timer = setInterval(adTick, 400);
  AD.on = true; adTick();
  return {on: true, ad: adShowing(), skipped: AD.skipped, closed: AD.closed};
};
L.ad_state = async () => ({ad: adShowing(), skippable: !!skipButton(), skipped: AD.skipped, closed: AD.closed, watching: AD.on,
                           muted_by_us: AD.muted_by_us, url: location.href});

// page-change events -> service worker -> agent
let lastUrl = location.href, timer = null;
function changed(kind) {
  clearTimeout(timer);
  timer = setTimeout(() => { try { chrome.runtime.sendMessage({type: "page_event", kind, url: location.href, title: document.title}); } catch (e) {} }, 400);
}
new MutationObserver(() => { if (location.href !== lastUrl) { lastUrl = location.href; changed("navigated"); } }).observe(document, {subtree: true, childList: true});
addEventListener("popstate", () => changed("navigated"));
if (document.readyState === "complete") changed("loaded"); else addEventListener("load", () => changed("loaded"));

// legacy: highlight at screen coordinates for vision clicks
chrome.runtime.onMessage.addListener((m) => {
  if (!m || m.type !== "pca-highlight") return;
  const x = m.x - window.screenX, y = m.y - window.screenY - (window.outerHeight - window.innerHeight);
  if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return;
  const e = document.elementFromPoint(x, y); if (e && e !== document.body) flash(e);
});

// 2.3.0: a livelier agent cursor. It glides for every action (find, read, wait, scroll, type), drifts over the area being read
// while the model thinks, and wanders toward likely next targets. One timer, transform-only CSS transitions, pointer-events:none,
// lives in the closed shadow overlay (never in snapshots / find / elementFromPoint). Respects prefers-reduced-motion.
const MOTION = {last: Date.now(), area: null, line: 0, timer: null, mode: "", busy: false};
const REDUCED = (() => { try { return matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return false; } })();
function vizReady() { return VIZ.on && VIZ.cursor; }
function moveTo(x, y, text, ms = 450) {
  if (!vizReady()) return;
  const r = vizHost(), cur = r.getElementById("cur"), lab = r.getElementById("lab");
  x = Math.max(4, Math.min(innerWidth - 20, x)); y = Math.max(4, Math.min(innerHeight - 20, y));
  cur.style.display = "block"; const ease = `transform ${ms}ms cubic-bezier(.22,.8,.3,1)`;
  cur.style.transition = ease; lab.style.transition = ease;
  cur.style.transform = `translate(${x - 3}px,${y - 2}px)`;
  if (text != null) { lab.style.display = text ? "block" : "none"; lab.textContent = String(text).slice(0, 60); }
  lab.style.transform = `translate(${Math.min(x + 18, innerWidth - 220)}px,${y + 18}px)`;
  VIZ.x = x; VIZ.y = y;
}
function touch(mode, area) { MOTION.last = Date.now(); if (mode != null) MOTION.mode = mode; if (area !== undefined) { MOTION.area = area; MOTION.line = 0; } ensureTimer(); }
function readArea() {
  const c = document.querySelector("article, main, [role=main], #content, #main, #search, #contents") || document.body;
  return c;
}
function visRect(e) {
  if (!e || !e.getBoundingClientRect) return null;
  const r = e.getBoundingClientRect(), l = Math.max(r.left, 8), t = Math.max(r.top, 40), rt = Math.min(r.right, innerWidth - 24), b = Math.min(r.bottom, innerHeight - 24);
  return rt - l > 30 && b - t > 20 ? {l, t, r: rt, b} : null;
}
function likelyTargets() {
  const out = [];
  for (const e of document.querySelectorAll('a[href] h3, input:not([type=hidden]), textarea, button, a#video-title, a#video-title-link, [role=button]')) {
    if (out.length > 12) break; const r = e.getBoundingClientRect();
    if (r.width > 8 && r.height > 8 && r.top > 40 && r.bottom < innerHeight - 10 && r.left >= 0 && r.right <= innerWidth && !isOverlay(e)) out.push(r);
  }
  return out;
}
function tick() {
  if (!vizReady()) { clearInterval(MOTION.timer); MOTION.timer = null; return; }
  if (MOTION.busy || document.hidden) return;
  const idle = Date.now() - MOTION.last;
  if (idle < 650) return;
  if (idle > 90000) return;  // nothing happening for a long time: stay put
  const area = visRect(MOTION.area) || visRect(readArea()) || {l: 40, t: 80, r: innerWidth - 60, b: innerHeight - 60};
  const reading = MOTION.mode === "reading" || MOTION.mode === "scanning";
  if (!reading && Math.random() < 0.35) {  // drift toward a likely next target (a result, a field, a button)
    const t = likelyTargets(); if (t.length) { const r = t[Math.floor(Math.random() * t.length)];
      moveTo(r.left + Math.min(r.width / 2, 60), r.top + r.height / 2, "thinking\u2026", REDUCED ? 0 : 900); return; }
  }
  // follow reading lines across the area: left -> right, then the next line down
  const lines = Math.max(3, Math.min(14, Math.floor((area.b - area.t) / 46))), n = MOTION.line++ % (lines * 2);
  const row = Math.floor(n / 2), right = n % 2 === 1;
  const y = area.t + 18 + row * ((area.b - area.t - 36) / Math.max(1, lines - 1)) + (Math.random() * 8 - 4);
  const x = right ? area.l + (area.r - area.l) * (0.6 + Math.random() * 0.3) : area.l + 10 + Math.random() * 30;
  moveTo(x, y, reading ? (MOTION.mode === "scanning" ? "looking at the page\u2026" : "reading\u2026") : "thinking\u2026", REDUCED ? 0 : (right ? 1100 : 700));
}
function ensureTimer() { if (!MOTION.timer && vizReady()) MOTION.timer = setInterval(tick, 950); }
function wrap(name, before, after) {
  const orig = L[name]; if (typeof orig !== "function") return;
  L[name] = async (...a) => {
    if (vizReady()) { MOTION.busy = true; try { await before(...a); } catch (e) {} finally { MOTION.busy = false; } }
    MOTION.last = Date.now();
    const res = await orig(...a);
    if (vizReady()) { try { await (after || (() => {}))(res, ...a); } catch (e) {} touch(); }
    return res;
  };
}
const glideEl = async (e, text, ms = 450) => { const r = e && e.getBoundingClientRect(); if (!r) return; moveTo(r.left + r.width / 2, r.top + r.height / 2, text, ms); await sleep(REDUCED ? 0 : ms); };
const origViz = L.viz;
L.viz = async (o = {}) => { const r = await origViz(o); if (o.on !== false) { touch("scanning", null); if (VIZ.cursor) moveTo(VIZ.x, VIZ.y, ""); } return r; };
wrap("snapshot", async () => { touch("scanning", readArea()); });
wrap("extract_text", async (args = {}) => {
  let e = null; try { e = args.id ? find(args.id) : readArea(); } catch (x) {}
  const v = visRect(e); if (v) moveTo(v.l + 10, v.t + 14, "reading\u2026", 500);
}, async (res, args = {}) => { let e = null; try { e = args.id ? find(args.id) : readArea(); } catch (x) {} touch("reading", e); });
wrap("find_text", async (args = {}) => { moveTo(innerWidth / 2, 90, `looking for "${String(args.text || "").slice(0, 36)}"`, 450); await sleep(REDUCED ? 0 : 300); },
  async (res) => { if (res && res.found && res.id) { let e = null; try { e = find(res.id); } catch (x) {} if (e) { await glideEl(e, "found " + (res.label || "").slice(0, 40), 500); touch("thinking", e); } } });
wrap("wait_for", async (args = {}) => {
  const v = visRect(readArea()) || {l: innerWidth / 3, t: innerHeight / 3, r: innerWidth * 2 / 3, b: innerHeight * 2 / 3};
  moveTo((v.l + v.r) / 2, (v.t + v.b) / 2, "waiting for " + String(args.text || args.selector || "the page").slice(0, 36), 500);
});
wrap("hover", async (id) => { await glideEl(find(id), "pointing at " + label(find(id)).slice(0, 40)); });
wrap("scroll", async (args = {}) => {
  const down = args.direction !== "up", area = visRect(readArea()) || {l: 40, t: 80, r: innerWidth - 60, b: innerHeight - 60};
  const x = Math.min(area.r - 30, innerWidth - 70);
  moveTo(x, down ? area.t + 40 : area.b - 40, "scrolling " + (down ? "down" : "up"), 250); await sleep(REDUCED ? 0 : 260);
  moveTo(x, down ? area.b - 40 : area.t + 40, null, 650);  // travel along the scroll area while the page moves
}, async () => { touch("scanning", readArea()); });
wrap("type", async (id, text) => {
  const e = find(id); await glideEl(e, "typing", 400);
  const r = e.getBoundingClientRect(), s = e.type === "password" ? "\u2022".repeat(String(text || "").length) : String(text || ""), lab = vizHost().getElementById("lab");
  const steps = Math.min(s.length, 24), per = REDUCED ? 0 : Math.max(18, Math.min(45, 700 / Math.max(1, steps)));
  for (let i = 1; i <= steps; i++) {  // caret walks across the field while the text appears in the label
    const shown = s.slice(0, Math.ceil(s.length * i / steps));
    moveTo(Math.min(r.left + 12 + (r.width - 24) * i / steps, r.right - 8), r.top + r.height / 2 + (i % 2 ? 1 : -1), null, per);
    lab.textContent = "typing \u201c" + (shown.length > 40 ? "\u2026" + shown.slice(-40) : shown) + "\u201d"; await sleep(per);
  }
});
wrap("click", async () => {}, async () => { MOTION.mode = "thinking"; });
L.viz_pos = () => ({x: Math.round(VIZ.x), y: Math.round(VIZ.y), mode: MOTION.mode, moving: !!MOTION.timer});
})();
