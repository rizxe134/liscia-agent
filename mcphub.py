"""3.0.0: MCP client (official `mcp` Python SDK). Servers live in config.yaml under mcp.servers (no secrets there):
  {name, transport: stdio|http|sse, command, args, env, url, enabled, tools: {tool: {enabled, always_allow}}, cached: [tool dicts]}
An auth header/token for a remote server is kept in the OS keychain ("mcp:<name>:auth"). Each call opens a short session
(spawn/connect -> initialize -> call -> close), so a crashed server never wedges the app. Logs: <data>/mcp_logs/<name>.log."""
import json, os, re, shutil, sys, threading, time

EXTRA_PATHS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", os.path.expanduser("~/.volta/bin"), os.path.expanduser("~/.local/bin"),
               r"C:\Program Files\nodejs", os.path.expandvars(r"%APPDATA%\npm")]
TIMEOUT = 45

def servers(cfg): return cfg.setdefault("mcp", {}).setdefault("servers", [])

def get_server(cfg, name): return next((s for s in servers(cfg) if s.get("name") == name), None)

def safe_name(n): return re.sub(r"[^A-Za-z0-9_-]+", "-", (n or "server").strip())[:40] or "server"

def demo_server():
    """The built-in demo server entry (runs this app/python with --mcp-demo)."""
    if getattr(sys, "frozen", False): cmd, args = sys.executable, ["--mcp-demo"]
    else: cmd, args = sys.executable, [os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcpdemo.py")]
    return {"name": "liscia-demo", "transport": "stdio", "command": cmd, "args": args, "env": {}, "enabled": True, "tools": {}}

FS_EXAMPLE = {"name": "filesystem", "transport": "stdio", "command": "npx",
              "args": ["-y", "@modelcontextprotocol/server-filesystem", os.path.expanduser("~/Documents")], "env": {}, "enabled": True, "tools": {}}

def log_path(name):
    import paths
    d = os.path.join(paths.data_dir(), "mcp_logs"); os.makedirs(d, exist_ok=True); return os.path.join(d, safe_name(name) + ".log")

def _log(name, msg):
    try:
        with open(log_path(name), "a", encoding="utf-8") as f: f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + redact(msg) + "\n")
    except OSError: pass

def redact(s):
    s = str(s)
    s = re.sub(r"(?i)\b(bearer|basic)\s+[^\s\"',]{6,}", r"\1 [hidden]", s)
    s = re.sub(r"(?i)(authorization|bearer|token|api[_-]?key|secret|password)([\"':= ]+)([^\s\"',]{6,})", r"\1\2[hidden]", s)
    return re.sub(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9-]{20,}|ntn_[A-Za-z0-9]{20,}|secret_[A-Za-z0-9]{20,}|ya29\.[\w-]{20,})", "[hidden]", s)

def read_log(name, n=80):
    try: return "".join(open(log_path(name), encoding="utf-8").readlines()[-n:])
    except OSError: return "(no log yet)"

def resolve_command(cmd):
    """GUI apps on macOS get a tiny PATH; look in the usual Node/Homebrew places too. Returns (path or None, PATH string)."""
    path = os.pathsep.join([os.environ.get("PATH", "")] + [p for p in EXTRA_PATHS if os.path.isdir(p)])
    if os.path.isabs(cmd or ""): return (cmd if os.path.exists(cmd) else None), path
    return shutil.which(cmd or "", path=path), path

def missing_hint(cmd):
    if os.path.basename(cmd or "") in ("npx", "node", "npm"):
        return ("Node.js isn't installed (couldn't find `npx`). Install it from https://nodejs.org (LTS), then press TEST again. "
                "Or try the built-in demo server, which needs nothing extra.")
    if os.path.basename(cmd or "") in ("uvx", "uv"):
        return "`uvx` isn't installed. Install uv from https://docs.astral.sh/uv/ then press TEST again."
    return f"Couldn't find the command `{cmd}`. Check the spelling or use its full path."

def _auth_headers(s):
    if s.get("transport") == "stdio": return {}
    import keystore
    v = keystore.get_secret(f"mcp:{safe_name(s['name'])}:auth")
    if not v: return {}
    if ":" in v and not v.lower().startswith("bearer "):
        k, val = v.split(":", 1); return {k.strip(): val.strip()}
    return {"Authorization": v if v.lower().startswith("bearer ") else "Bearer " + v}

async def _session_do(s, fn):
    from mcp import ClientSession
    name = s["name"]
    if s.get("transport", "stdio") == "stdio":
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        cmd, path = resolve_command(s.get("command"))
        if not cmd: raise FileNotFoundError(missing_hint(s.get("command")))
        env = dict(os.environ); env["PATH"] = path; env.update({k: str(v) for k, v in (s.get("env") or {}).items()})
        import keystore
        for k in s.get("secret_env") or []:  # env values kept in the keychain
            env[k] = keystore.get_secret(f"mcp:{safe_name(name)}:env:{k}")
        params = StdioServerParameters(command=cmd, args=[str(a) for a in s.get("args") or []], env=env)
        with open(log_path(name), "a", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as (r, w):
                async with ClientSession(r, w) as sess:
                    await sess.initialize(); return await fn(sess)
    elif s.get("transport") == "sse":
        from mcp.client.sse import sse_client
        async with sse_client(s["url"], headers=_auth_headers(s)) as (r, w):
            async with ClientSession(r, w) as sess:
                await sess.initialize(); return await fn(sess)
    else:
        from mcp.client.streamable_http import streamablehttp_client
        async with streamablehttp_client(s["url"], headers=_auth_headers(s)) as (r, w, _):
            async with ClientSession(r, w) as sess:
                await sess.initialize(); return await fn(sess)

def _run(s, fn, timeout=TIMEOUT):
    """Run an async MCP operation on a private event loop thread with a timeout."""
    import anyio
    box = {}
    def worker():
        async def main():
            with anyio.fail_after(timeout): return await _session_do(s, fn)
        try: box["v"] = anyio.run(main)
        except BaseException as e: box["e"] = e
    t = threading.Thread(target=worker, daemon=True); t.start(); t.join(timeout + 10)
    if t.is_alive(): raise TimeoutError(f"MCP server '{s['name']}' didn't answer in {timeout}s")
    if "e" in box:
        e = box["e"]
        while hasattr(e, "exceptions") and e.exceptions: e = e.exceptions[0]  # unwrap TaskGroup errors
        raise e if isinstance(e, Exception) else RuntimeError(str(e))
    return box.get("v")

def ga(o, *names, default=None):
    """mcp 1.x uses camelCase attributes, 2.x snake_case: take whichever exists."""
    for n in names:
        try:
            v = getattr(o, n)
            if v is not None: return v
        except AttributeError: pass
    return default

def tool_dict(t):
    ann = ga(t, "annotations")
    return {"name": t.name, "description": (ga(t, "description", default="") or "")[:500],
            "schema": ga(t, "input_schema", "inputSchema", default=None) or {"type": "object"},
            "read_only": bool(ann and ga(ann, "read_only_hint", "readOnlyHint", default=False)),
            "destructive": bool(ann and ga(ann, "destructive_hint", "destructiveHint", default=False))}

def list_tools(cfg, name):
    s = get_server(cfg, name)
    if not s: raise KeyError(name)
    _log(name, "list_tools")
    async def fn(sess):
        res = await sess.list_tools(); return [tool_dict(t) for t in res.tools]
    try: tools = _run(s, fn)
    except Exception as e: _log(name, f"ERROR list_tools: {type(e).__name__}: {e}"); raise
    s["cached"] = tools
    for t in tools: s.setdefault("tools", {}).setdefault(t["name"], {"enabled": True, "always_allow": False})
    _log(name, f"ok: {len(tools)} tools: " + ", ".join(t["name"] for t in tools)); return tools

def call_tool(cfg, name, tool, args):
    s = get_server(cfg, name)
    if not s: raise KeyError(name)
    _log(name, f"call {tool} {json.dumps(args)[:400]}")
    async def fn(sess):
        res = await sess.call_tool(tool, args or {})
        parts = []
        for c in res.content or []:
            parts.append(getattr(c, "text", None) or (f"[{getattr(c, 'type', 'content')}]"))
        sc = ga(res, "structured_content", "structuredContent")
        if sc and not parts: parts.append(json.dumps(sc)[:4000])
        return ("ERROR: " if ga(res, "is_error", "isError", default=False) else "") + "\n".join(parts)
    try: out = _run(s, fn)
    except Exception as e: _log(name, f"ERROR call {tool}: {type(e).__name__}: {e}"); raise
    _log(name, f"result {tool}: {out[:300]}"); return out

def enabled_tools(cfg, allowed=None):
    """[(server, tool dict, settings)] for enabled servers/tools; `allowed` = the bot's list of 'server' or 'server/tool' (None = all)."""
    out = []
    for s in servers(cfg):
        if not s.get("enabled", True): continue
        for t in s.get("cached") or []:
            st = (s.get("tools") or {}).get(t["name"], {"enabled": True, "always_allow": False})
            if not st.get("enabled", True): continue
            if allowed is not None and s["name"] not in allowed and f"{s['name']}/{t['name']}" not in allowed: continue
            out.append((s["name"], t, st))
    return out
