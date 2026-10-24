"""2.1.0: "open my github and give me a summary of the things I have" - uses the user's existing Chrome sign-in only.
Never types credentials: if GitHub isn't signed in, it stops and asks the user to sign in themselves."""
import collections, json, re, time
import creds

ASK = re.compile(r"\bmy\s+git\s?hub\b", re.I)
WANT = re.compile(r"summar|overview|what (do|have|i)|things|stuff|repos|repositor|projects|show me|tell me|give me|list", re.I)
RESERVED = {"login", "signup", "settings", "notifications", "explore", "marketplace", "pulls", "issues", "orgs", "features", "about",
            "pricing", "topics", "trending", "sponsors", "new", "codespaces", "dashboard", "search", "enterprise", "team", "collections",
            "events", "security", "site", "readme", "customer-stories", "solutions", "resources", "copilot", "apps", "contact"}

def wants_summary(task):
    return bool(ASK.search(task or "") and WANT.search(task or "") and not re.search(r"\bdesktop\b", task or "", re.I))

def signed_in(snap):
    els = snap.get("elements") or []
    if creds.auth_page(snap): return False
    return not any(re.search(r"github\.com/(login|signup)", e.get("href") or "") and re.search(r"sign (in|up)", e.get("label") or "", re.I) for e in els)

def username(snap):
    owners = collections.Counter()
    for e in snap.get("elements") or []:
        m = re.match(r"https://github\.com/([A-Za-z0-9-]{1,39})(?:/([\w.-]+))?/?$", e.get("href") or "")
        if m and m.group(1).lower() not in RESERVED:
            owners[m.group(1)] += 2 if m.group(2) else 1
            if re.search(r"your profile|signed in as", e.get("label") or "", re.I): owners[m.group(1)] += 50
    return owners.most_common(1)[0][0] if owners else ""

def github_summary(agent, link, task, logf, sleep=time.sleep):
    import webagent
    webagent.nav(link, "https://github.com/", agent.log); sleep(1.5)
    snap = link.call("snapshot", max=120)
    logf.write(json.dumps({"github": "dashboard", "url": snap.get("url"), "elements": len(snap.get("elements") or [])}) + "\n")
    if not signed_in(snap): return creds.sign_in_message(snap)
    user = username(snap)
    if not user: return "stopped: GitHub is open, but I couldn't tell which account is signed in, so I didn't summarize anything."
    url = f"https://github.com/{user}?tab=repositories"
    webagent.nav(link, url, agent.log); sleep(1.5)
    text = webagent.main_text(link, 5000)
    logf.write(json.dumps({"github": "repos", "user": user, "chars": len(text)}) + "\n")
    if not text: return f"stopped: opened {url} but couldn't read the page."
    q = (f"Summarize the GitHub account '{user}' for its owner from this repositories page: how many repositories are listed, then each "
         "main repository as a short line (name, public/private, language, one-line description, last updated). Plain text, no JSON in the answer.")
    ans = agent._answer_from(q, text, url)
    return f"Your GitHub ({user}):\n{ans}" if ans else f"stopped: opened your repositories ({url}) but couldn't summarize them."
