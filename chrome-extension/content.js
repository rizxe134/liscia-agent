// Draws a green outline where PC Agent is about to click (screen points -> this tab's viewport).
chrome.runtime.onMessage.addListener((m) => {
  if (!m || m.type !== "pca-highlight") return;
  const chromeTop = window.outerHeight - window.innerHeight;
  const x = m.x - window.screenX, y = m.y - window.screenY - chromeTop;
  if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return;  // click is outside this page
  const el = document.elementFromPoint(x, y);
  const r = el && el !== document.body && el !== document.documentElement ? el.getBoundingClientRect() : null;
  const box = document.createElement("div");
  const s = box.style;
  s.position = "fixed"; s.zIndex = 2147483647; s.pointerEvents = "none";
  s.border = "3px solid #00ff66"; s.boxShadow = "0 0 18px #00ff66"; s.borderRadius = "6px"; s.transition = "opacity .4s";
  if (r && r.width < innerWidth * 0.9 && r.height < innerHeight * 0.9) {
    s.left = r.left - 3 + "px"; s.top = r.top - 3 + "px"; s.width = r.width + "px"; s.height = r.height + "px";
  } else { s.left = x - 22 + "px"; s.top = y - 22 + "px"; s.width = "44px"; s.height = "44px"; s.borderRadius = "50%"; }
  const tag = document.createElement("div");
  tag.textContent = "PC Agent"; Object.assign(tag.style, {position: "absolute", top: "-20px", left: "0", background: "#000",
    color: "#00ff66", font: "11px Menlo, monospace", padding: "1px 5px", border: "1px solid #00ff66"});
  box.appendChild(tag); document.documentElement.appendChild(box);
  setTimeout(() => { s.opacity = "0"; setTimeout(() => box.remove(), 450); }, 1400);
});
