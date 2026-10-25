"""3.0.0: app connections (Google, Microsoft 365, GitHub, Notion, Spotify). Secrets (OAuth client, tokens) live only in the
OS keychain; config.yaml keeps just {connected, account}. OAuth = desktop loopback flow with PKCE (RFC 8252/7636):
a one-shot local http server on 127.0.0.1 receives the code, which is exchanged with the code_verifier.
Each connection exposes tools (name, description, JSON schema, write flag, run(args)). Write tools are always confirmed by the caller."""
import base64, datetime, hashlib, http.server, json, os, secrets, socket, threading, time, urllib.parse, webbrowser
import requests

def keystore():
    import keystore as k; return k

PROVIDERS = {
    "google": {"name": "Google (Calendar, Gmail, Drive)", "kind": "oauth",
               "auth": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
               "scopes": ["openid", "email", "https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/gmail.readonly",
                          "https://www.googleapis.com/auth/gmail.compose", "https://www.googleapis.com/auth/drive.readonly"],
               "extra": {"access_type": "offline", "prompt": "consent"}, "secret": True, "host": "127.0.0.1"},
    "microsoft": {"name": "Microsoft 365 (Outlook mail & calendar)", "kind": "oauth",
                  "auth": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                  "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                  "scopes": ["offline_access", "User.Read", "Mail.ReadWrite", "Calendars.ReadWrite"], "extra": {}, "secret": False, "host": "localhost"},
    "spotify": {"name": "Spotify", "kind": "oauth", "auth": "https://accounts.spotify.com/authorize", "token": "https://accounts.spotify.com/api/token",
                "scopes": ["user-read-playback-state", "user-modify-playback-state", "user-read-currently-playing"], "extra": {}, "secret": False,
                "host": "127.0.0.1", "port": 8766, "path": "/callback"},
    "github": {"name": "GitHub", "kind": "token", "token_hint": "a fine-grained personal access token (github.com/settings/tokens)"},
    "notion": {"name": "Notion", "kind": "token", "token_hint": "an internal integration secret (notion.so/profile/integrations), then share pages with it"},
}

HOWTO = {
"google": """Google needs your own (free) OAuth client - Liscia has no published Google app:
1. Open console.cloud.google.com, create a project (any name).
2. APIs & Services > Library: enable Google Calendar API, Gmail API and Google Drive API.
3. APIs & Services > OAuth consent screen: User type External, fill app name + your email, add yourself under Test users.
4. APIs & Services > Credentials > Create credentials > OAuth client ID > Application type: Desktop app.
5. Copy the Client ID and Client secret into the boxes here and press SAVE CLIENT, then CONNECT.
6. Your browser opens Google's consent page; pick your account and allow. You'll see "Connected" here.
Liscia only asks for: calendar events, read Gmail, create Gmail drafts (never sends), read Drive.""",
"microsoft": """1. Open entra.microsoft.com > App registrations > New registration (any name; Accounts: any org + personal).
2. Redirect URI: platform "Public client/native (mobile & desktop)", value http://localhost
3. API permissions: Microsoft Graph delegated: User.Read, Mail.ReadWrite, Calendars.ReadWrite, offline_access.
4. Copy the Application (client) ID here (no secret needed), SAVE CLIENT, then CONNECT.""",
"spotify": """1. developer.spotify.com/dashboard > Create app. Redirect URI: http://127.0.0.1:8766/callback  (Web API).
2. Copy the Client ID here (no secret needed), SAVE CLIENT, then CONNECT. Playback control needs Spotify Premium.""",
"github": "Create a fine-grained token at github.com/settings/tokens (repo read; Issues read/write if you want new issues), paste it, SAVE TOKEN.",
"notion": "notion.so/profile/integrations > New integration (internal) > copy the secret, paste it, SAVE TOKEN. Then open each page > ... > Connections > add it.",
}

def _k(pid, what): return f"conn:{pid}:{what}"

def client(pid):
    try: return json.loads(keystore().get_secret(_k(pid, "client")) or "{}")
    except ValueError: return {}

def save_client(pid, client_id, client_secret=""):
    keystore().set_secret(_k(pid, "client"), json.dumps({"client_id": client_id.strip(), "client_secret": (client_secret or "").strip()}))

def tokens(pid):
    try: return json.loads(keystore().get_secret(_k(pid, "token")) or "{}")
    except ValueError: return {}

def save_tokens(pid, tok): keystore().set_secret(_k(pid, "token"), json.dumps(tok))

def status(cfg, pid):
    c = cfg.setdefault("connections", {}).get(pid) or {}
    return {"connected": bool(c.get("connected")), "account": c.get("account", ""), "has_client": bool(c.get("has_client"))}

def mark(cfg, pid, **kw):
    cfg.setdefault("connections", {}).setdefault(pid, {}).update(kw)
    try:
        import settings; settings.save(cfg)
    except Exception: pass

def disconnect(cfg, pid):
    keystore().del_secret(_k(pid, "token")); mark(cfg, pid, connected=False, account="")

# ---------------- OAuth (loopback + PKCE) ----------------
def pkce_pair():
    v = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    ch = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    return v, ch

def auth_url(pid, redirect, challenge, state):
    p = PROVIDERS[pid]; c = client(pid)
    q = {"client_id": c.get("client_id", ""), "redirect_uri": redirect, "response_type": "code", "scope": " ".join(p["scopes"]),
         "code_challenge": challenge, "code_challenge_method": "S256", "state": state}
    q.update(p.get("extra") or {}); return p["auth"] + "?" + urllib.parse.urlencode(q)

PAGE = (b"<html><body style='background:#000;color:#3dff8f;font-family:monospace;padding:40px'><h2>Liscia Agent</h2>"
        b"<p>%s</p><p>You can close this tab.</p></body></html>")

def start_oauth(cfg, pid, open_browser=webbrowser.open, timeout=300, done=None):
    """Start the loopback flow in a thread. Returns the consent URL. done(ok, message) is called when it finishes."""
    p = PROVIDERS[pid]
    if not client(pid).get("client_id"): raise ValueError("Save your OAuth client ID first (see How to set up).")
    verifier, challenge = pkce_pair(); state = secrets.token_urlsafe(16); box = {}
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query))
            if q.get("state") != state or not (q.get("code") or q.get("error")):
                self.send_response(400); self.end_headers(); self.wfile.write(PAGE % b"Unexpected request."); return
            box.update(q); ok = "code" in q
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(PAGE % (b"Connected. Return to Liscia Agent." if ok else b"Not connected: " + q.get("error", "").encode()[:100]))
    srv = http.server.HTTPServer(("127.0.0.1", p.get("port", 0)), H); srv.timeout = 1
    port = srv.server_address[1]; redirect = f"http://{p.get('host', '127.0.0.1')}:{port}{p.get('path', '/')}"
    url = auth_url(pid, redirect, challenge, state)
    def wait():
        t0 = time.time()
        try:
            while not box and time.time() - t0 < timeout: srv.handle_request()
        finally: srv.server_close()
        if "code" not in box:
            if done: done(False, box.get("error") or "timed out waiting for the browser")
            return
        try:
            tok = exchange(pid, box["code"], redirect, verifier); save_tokens(pid, tok)
            acct = account_name(pid, tok)
            mark(cfg, pid, connected=True, account=acct)
            if done: done(True, f"Connected{(' as ' + acct) if acct else ''}.")
        except Exception as e:
            if done: done(False, f"token exchange failed: {type(e).__name__}: {str(e)[:200]}")
    threading.Thread(target=wait, daemon=True).start()
    open_browser(url); return url

def exchange(pid, code, redirect, verifier, post=None):
    p, c = PROVIDERS[pid], client(pid); post = post or requests.post
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "client_id": c["client_id"], "code_verifier": verifier}
    if c.get("client_secret"): data["client_secret"] = c["client_secret"]
    r = post(p["token"], data=data, timeout=30); r.raise_for_status(); tok = r.json()
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60; return tok

def access_token(pid, post=None):
    """A valid access token (refreshes when expired). Raises if not connected."""
    p = PROVIDERS[pid]
    if p["kind"] == "token":
        t = keystore().get_secret(_k(pid, "token"))
        if not t: raise PermissionError(f"{p['name']} isn't connected (Settings > CONNECTIONS).")
        return t
    tok = tokens(pid)
    if not tok.get("access_token"): raise PermissionError(f"{p['name']} isn't connected (Settings > CONNECTIONS).")
    if time.time() < tok.get("expires_at", 0): return tok["access_token"]
    if not tok.get("refresh_token"): raise PermissionError(f"{p['name']} sign-in expired - press CONNECT again.")
    c = client(pid); post = post or requests.post
    data = {"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": c.get("client_id", "")}
    if c.get("client_secret"): data["client_secret"] = c["client_secret"]
    r = post(p["token"], data=data, timeout=30); r.raise_for_status(); new = r.json()
    tok.update(new); tok["expires_at"] = time.time() + int(new.get("expires_in", 3600)) - 60; save_tokens(pid, tok)
    return tok["access_token"]

def api(pid, method, url, **kw):
    h = kw.pop("headers", {}); h["Authorization"] = ("token " if pid == "github" else "Bearer ") + access_token(pid)
    if pid == "notion": h["Notion-Version"] = "2022-06-28"
    if pid == "github": h["Accept"] = "application/vnd.github+json"
    r = requests.request(method, url, headers=h, timeout=30, **kw)
    if r.status_code >= 400: raise RuntimeError(f"{pid} API {r.status_code}: {r.text[:300]}")
    return r.json() if r.content and "json" in r.headers.get("Content-Type", "") else r.text

def account_name(pid, tok):
    try:
        if pid == "google": return requests.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": "Bearer " + tok["access_token"]}, timeout=15).json().get("email", "")
        if pid == "microsoft": return requests.get("https://graph.microsoft.com/v1.0/me", headers={"Authorization": "Bearer " + tok["access_token"]}, timeout=15).json().get("userPrincipalName", "")
        if pid == "spotify": return requests.get("https://api.spotify.com/v1/me", headers={"Authorization": "Bearer " + tok["access_token"]}, timeout=15).json().get("display_name", "")
    except Exception: return ""
    return ""

def save_token(cfg, pid, token):
    """GitHub/Notion: store the pasted token, verify it, mark connected."""
    keystore().set_secret(_k(pid, "token"), token)
    try:
        acct = api(pid, "GET", "https://api.github.com/user").get("login", "") if pid == "github" else \
               api(pid, "GET", "https://api.notion.com/v1/users/me").get("name", "")
    except Exception as e:
        keystore().del_secret(_k(pid, "token")); raise RuntimeError(f"that token didn't work: {str(e)[:160]}")
    mark(cfg, pid, connected=True, account=acct); return acct

# ---------------- tools ----------------
def _local_tz(): return datetime.datetime.now().astimezone().tzinfo

def _iso(s):
    """Accept '2026-10-26T15:00', with/without zone; return RFC3339 with the local offset."""
    d = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if d.tzinfo is None: d = d.replace(tzinfo=_local_tz())
    return d.isoformat()

def _end(start, end, minutes=60):
    return _iso(end) if end else (datetime.datetime.fromisoformat(_iso(start)) + datetime.timedelta(minutes=int(minutes or 60))).isoformat()

def _evs(items):
    out = []
    for e in items:
        st = e.get("start", {}); st = st.get("dateTime") or st.get("date") or ""
        out.append(f"- {st[:16].replace('T', ' ')}  {e.get('summary') or e.get('subject') or '(no title)'}  [id {e.get('id', '')[:60]}]")
    return "\n".join(out) or "(no events)"

def g_list_events(a):
    now = datetime.datetime.now(_local_tz()); days = int(a.get("days", 7) or 7)
    p = {"timeMin": _iso(a["from"]) if a.get("from") else now.isoformat(), "timeMax": (now + datetime.timedelta(days=days)).isoformat(),
         "singleEvents": "true", "orderBy": "startTime", "maxResults": int(a.get("max", 20) or 20)}
    if a.get("query"): p["q"] = a["query"]
    return _evs(api("google", "GET", "https://www.googleapis.com/calendar/v3/calendars/primary/events", params=p).get("items", []))

def g_create_event(a):
    body = {"summary": a["title"], "start": {"dateTime": _iso(a["start"])}, "end": {"dateTime": _end(a["start"], a.get("end"), a.get("minutes"))}}
    if a.get("description"): body["description"] = a["description"]
    if a.get("location"): body["location"] = a["location"]
    if a.get("attendees"): body["attendees"] = [{"email": x} for x in a["attendees"]]
    e = api("google", "POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events", json=body)
    return f"Created \"{e.get('summary')}\" on {e.get('start', {}).get('dateTime', '')[:16].replace('T', ' ')} ({e.get('htmlLink', '')})"

def g_update_event(a):
    body = {}
    if a.get("title"): body["summary"] = a["title"]
    if a.get("start"): body["start"] = {"dateTime": _iso(a["start"])}; body["end"] = {"dateTime": _end(a["start"], a.get("end"), a.get("minutes"))}
    if a.get("description"): body["description"] = a["description"]
    if a.get("location"): body["location"] = a["location"]
    e = api("google", "PATCH", f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{urllib.parse.quote(a['event_id'])}", json=body)
    return f"Updated \"{e.get('summary')}\"."

def g_delete_event(a):
    api("google", "DELETE", f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{urllib.parse.quote(a['event_id'])}")
    return "Deleted the event."

def g_gmail_search(a):
    r = api("google", "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages", params={"q": a.get("query", ""), "maxResults": int(a.get("max", 10) or 10)})
    out = []
    for m in r.get("messages", [])[:10]:
        d = api("google", "GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}", params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]})
        h = {x["name"]: x["value"] for x in d.get("payload", {}).get("headers", [])}
        out.append(f"- {h.get('Date', '')[:22]} | {h.get('From', '')[:40]} | {h.get('Subject', '')[:80]}  [id {m['id']}]\n  {d.get('snippet', '')[:160]}")
    return "\n".join(out) or "(no emails found)"

def _gm_text(p):
    if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(p["body"]["data"] + "==").decode("utf-8", "replace")
    return "\n".join(filter(None, (_gm_text(x) for x in p.get("parts", []) or [])))

def g_gmail_read(a):
    d = api("google", "GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{a['message_id']}", params={"format": "full"})
    h = {x["name"]: x["value"] for x in d.get("payload", {}).get("headers", [])}
    return f"From: {h.get('From')}\nSubject: {h.get('Subject')}\nDate: {h.get('Date')}\n\n" + (_gm_text(d.get("payload", {})) or d.get("snippet", ""))[:6000]

def g_gmail_draft(a):
    from email.mime.text import MIMEText
    m = MIMEText(a.get("body", "")); m["To"] = a["to"]; m["Subject"] = a.get("subject", "")
    raw = base64.urlsafe_b64encode(m.as_bytes()).decode()
    api("google", "POST", "https://gmail.googleapis.com/gmail/v1/users/me/drafts", json={"message": {"raw": raw}})
    return f"Draft saved in Gmail (to {a['to']}, subject \"{a.get('subject', '')}\"). It was NOT sent - open Gmail > Drafts to review and send."

def g_drive_search(a):
    q = "name contains '%s' or fullText contains '%s'" % ((a.get("query") or "").replace("'", ""),) * 2 if a.get("query") else None
    r = api("google", "GET", "https://www.googleapis.com/drive/v3/files", params={"q": q, "pageSize": 10, "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"} if q else {"pageSize": 10})
    return "\n".join(f"- {f['name']} ({f.get('mimeType', '').split('.')[-1]}, {f.get('modifiedTime', '')[:10]})  [id {f['id']}]" for f in r.get("files", [])) or "(no files)"

def g_drive_read(a):
    fid = a["file_id"]
    meta = api("google", "GET", f"https://www.googleapis.com/drive/v3/files/{fid}", params={"fields": "name,mimeType"})
    if meta.get("mimeType", "").startswith("application/vnd.google-apps"):
        txt = api("google", "GET", f"https://www.googleapis.com/drive/v3/files/{fid}/export", params={"mimeType": "text/plain"})
    else:
        txt = api("google", "GET", f"https://www.googleapis.com/drive/v3/files/{fid}", params={"alt": "media"})
    return f"{meta.get('name')}:\n" + str(txt)[:6000]

def ms_list_events(a):
    now = datetime.datetime.now(datetime.timezone.utc); days = int(a.get("days", 7) or 7)
    r = api("microsoft", "GET", "https://graph.microsoft.com/v1.0/me/calendarView",
            params={"startDateTime": now.isoformat(), "endDateTime": (now + datetime.timedelta(days=days)).isoformat(), "$top": 20, "$orderby": "start/dateTime"})
    return _evs(r.get("value", []))

def ms_create_event(a):
    tz = datetime.datetime.now().astimezone().tzname()
    body = {"subject": a["title"], "start": {"dateTime": _iso(a["start"]), "timeZone": "UTC" if False else tz},
            "end": {"dateTime": _end(a["start"], a.get("end"), a.get("minutes")), "timeZone": tz}}
    body["start"]["dateTime"] = body["start"]["dateTime"][:19]; body["end"]["dateTime"] = body["end"]["dateTime"][:19]
    e = api("microsoft", "POST", "https://graph.microsoft.com/v1.0/me/events", json=body)
    return f"Created \"{e.get('subject')}\" in Outlook."

def ms_mail_search(a):
    r = api("microsoft", "GET", "https://graph.microsoft.com/v1.0/me/messages", params={"$search": f"\"{a.get('query', '')}\"", "$top": 10})
    return "\n".join(f"- {m.get('receivedDateTime', '')[:16]} | {m.get('from', {}).get('emailAddress', {}).get('address', '')} | {m.get('subject', '')}\n  {m.get('bodyPreview', '')[:160]}" for m in r.get("value", [])) or "(no emails)"

def ms_draft(a):
    api("microsoft", "POST", "https://graph.microsoft.com/v1.0/me/messages",
        json={"subject": a.get("subject", ""), "body": {"contentType": "Text", "content": a.get("body", "")}, "toRecipients": [{"emailAddress": {"address": a["to"]}}]})
    return "Draft saved in Outlook (not sent)."

def gh_search(a):
    r = api("github", "GET", "https://api.github.com/search/issues", params={"q": a.get("query", "is:open assignee:@me"), "per_page": 10})
    return "\n".join(f"- {i['title']} ({i['html_url']})" for i in r.get("items", [])) or "(nothing found)"

def gh_create_issue(a):
    i = api("github", "POST", f"https://api.github.com/repos/{a['repo']}/issues", json={"title": a["title"], "body": a.get("body", "")})
    return f"Created issue #{i.get('number')}: {i.get('html_url')}"

def notion_search(a):
    r = api("notion", "POST", "https://api.notion.com/v1/search", json={"query": a.get("query", ""), "page_size": 10})
    out = []
    for p in r.get("results", []):
        t = "".join(x.get("plain_text", "") for v in (p.get("properties") or {}).values() if v.get("type") == "title" for x in v.get("title", []))
        out.append(f"- {t or '(untitled)'}  [id {p['id']}]")
    return "\n".join(out) or "(no pages shared with the integration)"

def notion_read(a):
    r = api("notion", "GET", f"https://api.notion.com/v1/blocks/{a['page_id']}/children", params={"page_size": 100})
    lines = []
    for b in r.get("results", []):
        rt = (b.get(b.get("type"), {}) or {}).get("rich_text", [])
        if rt: lines.append("".join(x.get("plain_text", "") for x in rt))
    return "\n".join(lines)[:6000] or "(empty page)"

def sp_search_play(a):
    r = api("spotify", "GET", "https://api.spotify.com/v1/search", params={"q": a["query"], "type": "track", "limit": 1})
    items = r.get("tracks", {}).get("items", [])
    if not items: return "No track found."
    t = items[0]; api("spotify", "PUT", "https://api.spotify.com/v1/me/player/play", json={"uris": [t["uri"]]})
    return f"Playing {t['name']} by {t['artists'][0]['name']} on Spotify."

def sp_control(a):
    act = a.get("action", "pause")
    m = {"pause": ("PUT", "pause"), "resume": ("PUT", "play"), "next": ("POST", "next"), "previous": ("POST", "previous")}[act]
    api("spotify", m[0], "https://api.spotify.com/v1/me/player/" + m[1]); return f"Spotify: {act}."

S = lambda props, req=(): {"type": "object", "properties": props, "required": list(req)}
STR, INT = {"type": "string"}, {"type": "integer"}
TOOLS = {
 "google": [
  ("calendar_list_events", "List upcoming Google Calendar events (optionally search).", S({"days": INT, "query": STR, "from": STR}), False, g_list_events),
  ("calendar_create_event", "Create a Google Calendar event. start/end are local ISO datetimes like 2026-10-26T15:00.",
   S({"title": STR, "start": STR, "end": STR, "minutes": INT, "description": STR, "location": STR, "attendees": {"type": "array", "items": STR}}, ("title", "start")), True, g_create_event),
  ("calendar_update_event", "Change a Google Calendar event (needs its id from calendar_list_events).", S({"event_id": STR, "title": STR, "start": STR, "end": STR, "minutes": INT, "description": STR, "location": STR}, ("event_id",)), True, g_update_event),
  ("calendar_delete_event", "Delete a Google Calendar event by id.", S({"event_id": STR}, ("event_id",)), True, g_delete_event),
  ("gmail_search", "Search Gmail (Gmail search syntax, e.g. 'from:amazon newer_than:7d').", S({"query": STR, "max": INT}), False, g_gmail_search),
  ("gmail_read", "Read one Gmail message by id.", S({"message_id": STR}, ("message_id",)), False, g_gmail_read),
  ("gmail_draft", "Create a Gmail DRAFT (never sends).", S({"to": STR, "subject": STR, "body": STR}, ("to", "body")), True, g_gmail_draft),
  ("drive_search", "Search Google Drive files by name/text.", S({"query": STR}), False, g_drive_search),
  ("drive_read", "Read a Google Drive file's text by id.", S({"file_id": STR}, ("file_id",)), False, g_drive_read)],
 "microsoft": [
  ("outlook_list_events", "List upcoming Outlook calendar events.", S({"days": INT}), False, ms_list_events),
  ("outlook_create_event", "Create an Outlook calendar event (local ISO start).", S({"title": STR, "start": STR, "end": STR, "minutes": INT}, ("title", "start")), True, ms_create_event),
  ("outlook_mail_search", "Search Outlook mail.", S({"query": STR}), False, ms_mail_search),
  ("outlook_draft", "Create an Outlook mail DRAFT (never sends).", S({"to": STR, "subject": STR, "body": STR}, ("to", "body")), True, ms_draft)],
 "github": [
  ("github_search", "Search GitHub issues/PRs (GitHub search syntax).", S({"query": STR}), False, gh_search),
  ("github_create_issue", "Create a GitHub issue in owner/repo.", S({"repo": STR, "title": STR, "body": STR}, ("repo", "title")), True, gh_create_issue)],
 "notion": [
  ("notion_search", "Search Notion pages shared with the integration.", S({"query": STR}), False, notion_search),
  ("notion_read_page", "Read a Notion page's text by id.", S({"page_id": STR}, ("page_id",)), False, notion_read)],
 "spotify": [
  ("spotify_play", "Search a song on Spotify and play it on the active device.", S({"query": STR}, ("query",)), False, sp_search_play),
  ("spotify_control", "Spotify playback: pause, resume, next, previous.", S({"action": {"type": "string", "enum": ["pause", "resume", "next", "previous"]}}, ("action",)), False, sp_control)],
}

def tools_for(cfg, allowed=None):
    """Tool dicts for connected providers (allowed = the bot's connection list; None = all connected)."""
    out = []
    for pid, lst in TOOLS.items():
        if not status(cfg, pid)["connected"]: continue
        if allowed is not None and pid not in allowed: continue
        for name, desc, schema, write, fn in lst:
            out.append({"name": name, "description": desc, "schema": schema, "write": write, "source": pid, "run": fn})
    return out
