"""Fast, non-vision path for browsers on macOS: read the page's clickable elements from
Safari / Google Chrome via AppleScript + JavaScript, and click them by id.

One-time setup (else we silently fall back to screenshots):
  Safari: Settings > Advanced > "Show features for web developers", then Develop > "Allow JavaScript from Apple Events"
  Chrome: View > Developer > "Allow JavaScript from Apple Events"
  macOS will also ask to let PC Agent/Python control Safari/Chrome (Automation) - click OK."""
import json, re, subprocess, sys

BROWSERS = {"Safari": "safari", "Google Chrome": "chrome", "Brave Browser": "chrome",
            "Microsoft Edge": "chrome", "Arc": "chrome"}

COLLECT_JS = r"""
(function(){
 var sel='a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link],[role=tab],[role=menuitem],[role=option],[onclick],[contenteditable=true],summary,ytd-thumbnail,[tabindex]:not([tabindex="-1"])';
 var els=[].slice.call(document.querySelectorAll(sel)), out=[], seen=new Set();
 var top=window.screenY+(window.outerHeight-window.innerHeight), left=window.screenX;
 window.__pca=[];
 for(var i=0;i<els.length && out.length<__MAX__;i++){
  var e=els[i], r=e.getBoundingClientRect();
  if(r.width<4||r.height<4||r.bottom<0||r.right<0||r.top>innerHeight||r.left>innerWidth) continue;
  var st=getComputedStyle(e); if(st.visibility=='hidden'||st.display=='none'||st.opacity=='0') continue;
  var t=(e.getAttribute('aria-label')||e.innerText||e.value||e.placeholder||e.title||e.alt||'').replace(/\s+/g,' ').trim().slice(0,70);
  if(!t){var im=e.querySelector&&e.querySelector('img[alt]'); if(im) t=im.alt.slice(0,70);}
  var key=t+'|'+Math.round(r.left/10)+'|'+Math.round(r.top/10); if(seen.has(key)) continue; seen.add(key);
  var id=window.__pca.length; window.__pca.push(e);
  out.push({id:id,tag:e.tagName.toLowerCase(),type:e.type||e.getAttribute('role')||'',text:t,
   x:Math.round(left+r.left+r.width/2),y:Math.round(top+r.top+r.height/2)});
 }
 return JSON.stringify({url:location.href,title:document.title,elements:out});
})()
"""

def _osascript_js(app, js, run=subprocess.run):
    kind = BROWSERS.get(app)
    if kind == "safari":
        line = f'tell application "{app}" to do JavaScript (item 1 of argv) in current tab of front window'
    elif kind == "chrome":
        line = f'tell application "{app}" to execute active tab of front window javascript (item 1 of argv)'
    else:
        return None
    r = run(["osascript", "-e", "on run argv", "-e", line, "-e", "end run", "--", js],
            capture_output=True, text=True, timeout=8)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "").strip()[:200])
    return r.stdout.strip()

def run_js(app, js, run=subprocess.run):
    """Public helper: run JavaScript in the front tab of a browser app."""
    return _osascript_js(app, js, run)

def frontmost_app(run=subprocess.run):
    """Name of the frontmost app (no special permissions needed)."""
    if sys.platform != "darwin":
        return None
    try:
        asn = run(["lsappinfo", "front"], capture_output=True, text=True, timeout=3).stdout.strip()
        out = run(["lsappinfo", "info", "-only", "name", asn], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r'=\s*"([^"]+)"', out)
        return m.group(1) if m else None
    except Exception:
        return None

def recent_browser(run=subprocess.run):
    """Most recently used running browser (front-to-back window order), or None."""
    if sys.platform != "darwin":
        return None
    try:
        out = run(["lsappinfo", "visibleProcessList"], capture_output=True, text=True, timeout=3).stdout
        for name in re.findall(r'"([^"]+)"', out):
            name = name.replace("_", " ")
            if name in BROWSERS:
                return name
    except Exception:
        pass
    return None

class BrowserDOM:
    def __init__(self, max_elements=60, run=subprocess.run, log=print):
        self.max, self.run, self.log = max_elements, run, log
        self.app, self.warned = None, set()

    def snapshot(self):
        """Return {'app','url','title','elements':[...]} for the frontmost browser, or None."""
        app = frontmost_app(self.run)
        if app not in BROWSERS:
            return None
        try:
            raw = _osascript_js(app, COLLECT_JS.replace("__MAX__", str(self.max)), self.run)
            data = json.loads(raw)
        except Exception as e:
            if app not in self.warned:
                self.warned.add(app)
                self.log(f"(fast page reading unavailable in {app}: {e}. Enable 'Allow JavaScript from Apple Events' "
                         f"in {app}'s Develop menu for faster, more accurate clicks. Using screenshots.)")
            return None
        self.app = app; data["app"] = app
        return data

    def click(self, element_id):
        js = (f"(function(){{var e=(window.__pca||[])[{int(element_id)}]; if(!e) return 'missing';"
              "e.scrollIntoView({block:'center'}); e.style.outline='3px solid #00ff66'; e.style.outlineOffset='2px'; setTimeout(function(){e.style.outline='';},1500); e.focus(); setTimeout(function(){e.click();},350); return 'ok';})()")
        res = _osascript_js(self.app, js, self.run)
        if res != "ok":
            raise RuntimeError(f"element {element_id} not found (page changed?)")

def format_elements(snap):
    lines = [f"BROWSER: {snap.get('app')} | {snap.get('title','')[:80]} | {snap.get('url','')[:120]}",
             "CLICKABLE ELEMENTS on the page, in page order (id, kind, visible text).",
             "Choose by reading the TEXT: the element whose text best matches what the task needs next",
             "(e.g. for 'first video' pick the first element whose text is a video title, not navigation links).",
             "Then reply with click_element and that id. Write your reasoning in \"thought\" first."]
    for e in snap.get("elements", []):
        kind = e["tag"] + (f"[{e['type']}]" if e.get("type") else "")
        lines.append(f"  [{e['id']}] {kind} \"{e['text']}\"")
    return "\n".join(lines)
