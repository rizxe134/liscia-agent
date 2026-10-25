"""3.0.0: one tool list per bot = its app connections + its MCP tools + its memory. Before the normal task flow, the model gets
the list and either picks ONE tool (name + JSON args, validated against the tool's JSON schema) or says none. Write tools
(and MCP tools not marked read-only) need an Approve in the chat unless the user ticked "always allow" for that MCP tool."""
import datetime, json, re


def memory_tools(store, cid):
    def remember(a): return "Saved. I'll remember: " + store.remember(cid, a["note"])[-1]
    def recall(a):
        mem = (store.get(cid) or {}).get("bot", {}).get("memory") or []
        return "\n".join(f"- {m}" for m in mem) or "(nothing saved yet)"
    return [{"name": "memory_save", "description": "Save a short note to this bot's memory (facts/preferences the user asks you to remember).",
             "schema": {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}, "write": False, "source": "memory", "run": remember},
            {"name": "memory_list", "description": "List what this bot has saved in its memory.", "schema": {"type": "object", "properties": {}},
             "write": False, "source": "memory", "run": recall}]

def bot_tools(cfg, bot, store=None, cid=None):
    import connections, mcphub
    tools = []
    import bots
    try: tools += connections.tools_for(cfg, bots.allowed(bot, "connections"))
    except Exception: pass
    allowed = bots.allowed(bot, "mcp")
    for server, t, st in mcphub.enabled_tools(cfg, allowed):
        write = not t.get("read_only") and not st.get("always_allow")
        tools.append({"name": f"{server}__{t['name']}", "description": f"[MCP {server}] {t['description']}", "schema": t["schema"],
                      "write": write, "source": f"mcp:{server}", "mcp": (server, t["name"]),
                      "run": (lambda a, s=server, n=t["name"]: mcphub.call_tool(cfg, s, n, a))})
    if store is not None and cid: tools += memory_tools(store, cid)
    return tools

SOURCE_WORDS = {
    "memory": r"remember|memori[sz]e|memory|what do you know about me|forget",
    "google": r"calendar|meeting|event|schedule|appointment|agenda|busy|free time|email|e-mail|mail|inbox|gmail|draft|drive|google doc|document",
    "microsoft": r"calendar|meeting|event|schedule|appointment|agenda|email|e-mail|mail|inbox|outlook|draft",
    "github": r"github|issue|pull request|\bprs?\b|repo",
    "notion": r"notion|page|notes?\b",
    "spotify": r"spotify",
}

def relevant(task, tools):
    """Cheap gate: only ask the model when the request plausibly needs one of these tools."""
    t = (task or "").lower()
    for tl in tools:
        src = tl["source"]
        if src.startswith("mcp:"):
            words = [src[4:].lower(), tl["mcp"][1].replace("_", " ").lower()] + re.findall(r"[a-z]{5,}", tl["mcp"][1].replace("_", " ").lower())
            if re.search(r"\b(mcp|tool)\b", t) or any(w and w in t for w in words): return True
        elif re.search(r"\b(" + SOURCE_WORDS.get(src, "$^") + r")", t): return True
    return False

PICK = ("You can call ONE tool to handle the user's request, or none. Today is {today} (local time {now}, UTC offset {tz}).\n"
        "TOOLS (name: description; args JSON schema):\n{tools}\n\n"
        "Reply with ONE JSON object only: {{\"tool\": \"<name>\", \"args\": {{...}}}} or {{\"tool\": \"none\"}}.\n"
        "Use none for anything the tools can't do (web browsing, opening apps, playing YouTube, general chat). "
        "Datetimes: local ISO like 2026-10-26T15:00 (no zone). Never invent ids; list first if you need one.")

def pick(client, task, tools, persona="", history=()):
    now = datetime.datetime.now().astimezone()
    lines = [f"- {t['name']}: {t['description'][:200]} | args {json.dumps(t['schema'].get('properties', {}))[:400]}"
             + (f" required {t['schema'].get('required')}" if t['schema'].get('required') else "") for t in tools[:60]]
    sys_p = (persona + "\n\n" if persona else "") + PICK.format(today=now.strftime("%A %Y-%m-%d"), now=now.strftime("%H:%M"),
                                                             tz=now.strftime("%z"), tools="\n".join(lines))
    raw = client.text_chat([{"role": "system", "content": sys_p}] + list(history)[-4:] + [{"role": "user", "content": task}],
                           json_mode=True, num_predict=400)
    try: obj = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError: return None
    name = str(obj.get("tool") or "none")
    if name == "none": return None
    tool = next((t for t in tools if t["name"] == name), None)
    if not tool: return None
    return tool, obj.get("args") if isinstance(obj.get("args"), dict) else {}

def validate(schema, args):
    """Returns an error string or ''. jsonschema when available, else required/type checks."""
    try:
        import jsonschema
        try: jsonschema.validate(args, schema or {"type": "object"}); return ""
        except jsonschema.ValidationError as e: return e.message
    except ImportError: pass
    for k in (schema or {}).get("required", []):
        if k not in args: return f"missing '{k}'"
    types = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    for k, v in args.items():
        ty = ((schema or {}).get("properties", {}).get(k) or {}).get("type")
        if ty in types and not isinstance(v, types[ty]): return f"'{k}' should be {ty}"
    return ""

def describe(tool, args):
    a = "\n".join(f"   {k}: {json.dumps(v, ensure_ascii=False)[:200]}" for k, v in args.items()) or "   (no arguments)"
    return f"{tool['name']}  ({tool['source']})\n{a}"

def run(tool, args, confirm, log=print):
    """Validate, confirm writes, execute. Returns (ok, text)."""
    err = validate(tool["schema"], args)
    if err: return False, f"The model gave bad arguments for {tool['name']}: {err}"
    if tool.get("write"):
        if not confirm("The bot wants to run a tool that changes something:\n\n" + describe(tool, args)):
            return False, "Cancelled - nothing was changed."
    log(f"[tool] {tool['name']} {json.dumps(args, ensure_ascii=False)[:200]}")
    try: return True, str(tool["run"](args))
    except Exception as e: return False, f"{tool['name']} failed: {type(e).__name__}: {str(e)[:300]}"

def answer(client, task, tool, result, persona=""):
    """Turn a tool result into a short reply in the bot's voice."""
    sys_p = (persona + "\n\n" if persona else "") + ("Answer the user's request using ONLY the tool result below. Be brief and concrete "
             "(lists for many items). If it failed or was cancelled, say so plainly.")
    try:
        out = client.text_chat([{"role": "system", "content": sys_p},
                                {"role": "user", "content": f"REQUEST: {task}\nTOOL {tool['name']} RESULT:\n{result[:6000]}"}], num_predict=500)
        return (out or "").strip() or result
    except Exception: return result

def try_tools(client, task, tools, confirm, persona="", history=(), log=print):
    """Returns reply text if a tool handled the request, else None."""
    if not relevant(task, tools): return None
    choice = pick(client, task, tools, persona, history)
    if not choice: return None
    tool, args = choice
    ok, res = run(tool, args, confirm, log)
    if not ok and res.startswith("Cancelled"): return res
    return answer(client, task, tool, res, persona) if ok else res
