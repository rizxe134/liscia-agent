// Liscia Agent content script: page snapshots + DOM actions, driven by the service worker.
(() => {
if (window.__liscia) return;  // injected twice (manifest + on-demand) -> keep the first
const L = window.__liscia = {};
const SEL = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[role=tab],' +
  '[role=menuitem],[role=option],[role=checkbox],[role=radio],[role=switch],[role=combobox],[role=searchbox],[role=textbox],' +
  '[contenteditable=""],[contenteditable=true],[onclick],[tabindex]:not([tabindex="-1"])';
let nextId = 1;

function visible(e) {
  const r = e.getBoundingClientRect();
  if (r.width < 3 || r.height < 3 || r.bottom < 0 || r.right < 0 || r.top > innerHeight || r.left > innerWidth) return false;
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
L.snapshot = (opts = {}) => {
  const max = opts.max || 80, out = [], seen = new Set();
  for (const e of document.querySelectorAll(SEL)) {
    if (out.length >= max) break;
    if (!visible(e) || e.closest("[aria-hidden=true]")) continue;
    const r = e.getBoundingClientRect(), text = label(e);
    const key = text + "|" + Math.round(r.left / 8) + "|" + Math.round(r.top / 8);
    if (seen.has(key)) continue; seen.add(key);
    const el = {id: idOf(e), role: role(e), label: text, tag: e.tagName.toLowerCase(),
      bbox: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)]};
    if ("value" in e && e.value && el.role !== "button") el.value = String(e.value).slice(0, 80);
    if (e.href) el.href = e.href.slice(0, 160);
    if (e.disabled) el.disabled = true;
    if (e.checked) el.checked = true;
    if (document.activeElement === e) el.focused = true;
    out.push(el);
  }
  return {url: location.href, title: document.title, elements: out, dialogs: dialogs(), text: summary(opts.text || 1200),
    scroll: [Math.round(scrollY), Math.round(document.documentElement.scrollHeight - innerHeight)],
    viewport: [innerWidth, innerHeight], ready: document.readyState};
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
function center(e) { const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }
function mouse(e, type, x, y) {
  const o = {bubbles: true, cancelable: true, composed: true, view: window, clientX: x, clientY: y, button: 0, buttons: type.endsWith("down") ? 1 : 0};
  e.dispatchEvent(type.startsWith("pointer") ? new PointerEvent(type, {...o, pointerId: 1, pointerType: "mouse", isPrimary: true}) : new MouseEvent(type, o));
}
L.prepare = async (id) => {  // scroll into view + highlight; returns viewport centre for a trusted click fallback
  const e = find(id); e.scrollIntoView({block: "center", inline: "center"}); await sleep(120); flash(e); await sleep(350);
  const [x, y] = center(e); return {x, y, label: label(e)};
};
L.click = async (id) => {
  const e = find(id), [x, y] = center(e);
  const target = document.elementFromPoint(x, y) || e;
  const hit = (target === e || e.contains(target)) ? target : e;
  for (const t of ["pointerover", "mouseover", "pointerdown", "mousedown"]) mouse(hit, t, x, y);
  if (e.focus) e.focus({preventScroll: true});
  for (const t of ["pointerup", "mouseup"]) mouse(hit, t, x, y);
  hit.click();
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
  if (args.id) { find(args.id).scrollIntoView({block: "center"}); return {scrolled: "to element"}; }
  const dy = args.amount != null ? Number(args.amount) : (args.direction === "up" ? -0.8 : 0.8) * innerHeight;
  window.scrollBy({top: dy, behavior: "instant"}); await sleep(200); return {scrollY: Math.round(scrollY)};
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
    if (visible(e) && e.href && e.href.includes("/watch") && !e.closest("ytd-ad-slot-renderer,ytd-in-feed-ad-layout-renderer")) {
      const id = idOf(e); await L.prepare(id); await L.click(id); return {clicked: label(e), href: e.href};
    }
  }
  throw new Error("no video link on this page");
};

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
})();
