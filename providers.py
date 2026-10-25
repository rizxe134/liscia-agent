"""Model providers (2.0.0): one interface for chat, JSON / structured output and vision across
Local (Ollama), OpenAI, Anthropic Claude and Google Gemini. Plain HTTPS via requests (no SDKs).
Client interface (what the agent uses):
  chat(system, prompt, image, on_token=None) -> str          vision step (JSON text expected)
  text_chat(messages, json_mode=False, on_token=None, num_predict=None, model=None, schema=None, temperature=None) -> str
  check() -> [model names] | None;  preload();  .model .text_model .num_predict .provider"""
import base64, io, json, time
import requests
import keystore

NAMES = {"ollama": "Local (Ollama)", "openai": "OpenAI", "anthropic": "Anthropic Claude", "gemini": "Google Gemini"}
# fallback lists (the Settings page fetches the live list from each provider's models API when a key is set)
STATIC_MODELS = {
    "openai": {"text": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o", "o4-mini"], "vision": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o", "gpt-4o-mini"]},
    "anthropic": {"text": ["claude-sonnet-4-5", "claude-haiku-4-5", "claude-opus-4-1"], "vision": ["claude-sonnet-4-5", "claude-haiku-4-5", "claude-opus-4-1"]},
    "gemini": {"text": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"], "vision": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"]},
}
DEFAULTS = {p: {"text_model": m["text"][0], "vision_model": m["vision"][0]} for p, m in STATIC_MODELS.items()}
PRIVACY = ("Cloud providers (OpenAI, Anthropic, Google) receive your messages and, for computer/browser tasks, "
           "screenshots of your screen and the content of web pages. That data leaves this computer and is handled under "
           "that company's terms. Local (Ollama) keeps everything on this computer and stays the default.")

class ProviderError(Exception):
    """kind: auth | quota | network | model | bad_request | server | no_key"""
    def __init__(self, provider, kind, msg):
        super().__init__(f"{NAMES.get(provider, provider)}: {msg}"); self.provider, self.kind = provider, kind

def png_b64(image):
    buf = io.BytesIO(); image.save(buf, format="PNG"); return base64.b64encode(buf.getvalue()).decode()

def json_text(raw):
    """Strip ```json fences some cloud models add."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        s = s.rsplit("```", 1)[0]
    return s.strip()

class CloudClient:
    URLS = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta"}

    def __init__(self, provider, text_model, vision_model, key=None, timeout_s=60, retries=2, num_predict=200, temperature=0.1,
                 post=None, get=None, sleep=time.sleep):
        self.provider, self.text_model, self.model = provider, text_model, vision_model
        self.key = key if key is not None else keystore.get(provider)
        self.timeout, self.retries, self.num_predict, self.temperature = timeout_s, retries, num_predict, temperature
        self._post, self._get, self._sleep = post or requests.post, get or requests.get, sleep
        self.fallback = ""

    # ---------- request building (pure, tested) ----------
    def _headers(self):
        if self.provider == "openai": return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if self.provider == "anthropic": return {"x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        return {"x-goog-api-key": self.key, "Content-Type": "application/json"}

    def build(self, model, messages, image_b64=None, json_mode=False, schema=None, max_tokens=512, temperature=0.1):
        """messages: [{'role': system|user|assistant, 'content': str}]. The image (if any) goes with the last user message."""
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        if schema: system += "\n\nReply with ONLY a JSON object matching this JSON schema:\n" + json.dumps(schema)
        elif json_mode: system += "\n\nReply with ONLY a valid JSON object, no other text."
        conv = [m for m in messages if m["role"] != "system"]
        last_user = max((i for i, m in enumerate(conv) if m["role"] == "user"), default=-1)
        p = self.provider
        if p == "openai":
            msgs = ([{"role": "system", "content": system}] if system else [])
            for i, m in enumerate(conv):
                if i == last_user and image_b64:
                    msgs.append({"role": "user", "content": [{"type": "text", "text": m["content"]},
                                 {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_b64, "detail": "high"}}]})
                else: msgs.append({"role": m["role"], "content": m["content"]})
            body = {"model": model, "messages": msgs, "max_completion_tokens": max_tokens}
            if not model.startswith(("o1", "o3", "o4", "gpt-5")): body["temperature"] = temperature
            if json_mode or schema: body["response_format"] = {"type": "json_object"}
            return f"{self.URLS[p]}/chat/completions", body
        if p == "anthropic":
            msgs = []
            for i, m in enumerate(conv):
                if i == last_user and image_b64:
                    msgs.append({"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                                                            {"type": "text", "text": m["content"]}]})
                else: msgs.append({"role": m["role"], "content": m["content"]})
            body = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "messages": msgs}
            if system: body["system"] = system
            return f"{self.URLS[p]}/messages", body
        contents = []
        for i, m in enumerate(conv):
            parts = [{"text": m["content"]}]
            if i == last_user and image_b64: parts.append({"inline_data": {"mime_type": "image/png", "data": image_b64}})
            contents.append({"role": "model" if m["role"] == "assistant" else "user", "parts": parts})
        gen = {"maxOutputTokens": max_tokens, "temperature": temperature}
        if json_mode or schema: gen["responseMimeType"] = "application/json"
        if model.startswith("gemini-2.5"): gen["thinkingConfig"] = {"thinkingBudget": 0 if "pro" not in model else 128}
        else: gen["maxOutputTokens"] = max_tokens + 2048  # 2.3.5: newer Gemini models think first; leave room or the reply comes back empty (MAX_TOKENS)
        body = {"contents": contents, "generationConfig": gen}
        if system: body["systemInstruction"] = {"parts": [{"text": system}]}
        return f"{self.URLS[p]}/models/{model}:generateContent", body

    def parse(self, data):
        p = self.provider
        try:
            if p == "openai": return data["choices"][0]["message"]["content"] or ""
            if p == "anthropic": return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
            return "".join(pt.get("text", "") for pt in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError):
            raise ProviderError(p, "server", f"unexpected reply: {json.dumps(data)[:200]}")

    def _error(self, r):
        try: detail = r.json(); detail = (detail.get("error") or {}).get("message") if isinstance(detail.get("error"), dict) else detail.get("error") or detail
        except Exception: detail = r.text
        detail = str(detail)[:200]
        if r.status_code in (401, 403): return ProviderError(self.provider, "auth", f"the API key was rejected ({r.status_code}). Check it in Settings. {detail}")
        if r.status_code == 429: return ProviderError(self.provider, "quota", f"rate limit or quota exceeded (429). Check your plan/billing. {detail}")
        if r.status_code == 404: return ProviderError(self.provider, "model", f"model not found (404). Pick another model in Settings. {detail}")
        if r.status_code >= 500: return ProviderError(self.provider, "server", f"server error {r.status_code}. {detail}")
        return ProviderError(self.provider, "bad_request", f"request rejected ({r.status_code}): {detail}")

    def request(self, url, body):
        if not self.key: raise ProviderError(self.provider, "no_key", "no API key set. Add one in Settings (gear button), or switch to Local (Ollama).")
        last = None
        for attempt in range(self.retries + 1):
            try:
                r = self._post(url, json=body, headers=self._headers(), timeout=self.timeout)
            except requests.exceptions.Timeout:
                last = ProviderError(self.provider, "network", f"timed out after {self.timeout}s")
            except requests.exceptions.RequestException as e:
                last = ProviderError(self.provider, "network", f"network error ({type(e).__name__}). Are you online?")
            else:
                if r.status_code == 200: return self.parse(r.json())
                last = self._error(r)
                if last.kind not in ("quota", "server"): raise last
            if attempt < self.retries: self._sleep(1.5 * (attempt + 1))
        raise last

    # ---------- agent interface ----------
    def chat(self, system, prompt, image, on_token=None):
        url, body = self.build(self.model, [{"role": "system", "content": system}, {"role": "user", "content": prompt}], png_b64(image),
                               json_mode=True, max_tokens=max(self.num_predict, 300), temperature=self.temperature)
        out = json_text(self.request(url, body))
        if on_token and out: on_token(out)
        return out

    def text_chat(self, messages, json_mode=False, on_token=None, num_predict=None, model=None, schema=None, temperature=None):
        url, body = self.build(model or self.text_model, messages, None, json_mode=json_mode, schema=schema,
                               max_tokens=num_predict or 512, temperature=0.3 if temperature is None else temperature)
        out = self.request(url, body)
        if json_mode or schema: out = json_text(out)
        if on_token and out: on_token(out)
        return out

    def preload(self): pass

    def check(self):
        try: return list_models(self.provider, self.key, get=self._get)["text"]
        except Exception: return None

def list_models(provider, key, get=None, timeout=15):
    """Live model list from the provider's models API -> {'text': [...], 'vision': [...]}. Raises ProviderError."""
    get = get or requests.get
    if not key: raise ProviderError(provider, "no_key", "no API key set.")
    try:
        if provider == "openai":
            r = get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=timeout)
        elif provider == "anthropic":
            r = get("https://api.anthropic.com/v1/models?limit=100", headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=timeout)
        else:
            r = get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers={"x-goog-api-key": key}, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise ProviderError(provider, "network", f"network error ({type(e).__name__}). Are you online?")
    if r.status_code != 200:
        raise CloudClient(provider, "", "", key="x")._error(r)
    data = r.json()
    if provider == "openai":
        ids = sorted((m["id"] for m in data.get("data", []) if m["id"].startswith(("gpt-", "o1", "o3", "o4", "chatgpt"))
                      and not any(x in m["id"] for x in ("audio", "realtime", "transcribe", "tts", "image", "search", "embedding", "instruct"))), reverse=True)
        vis = [i for i in ids if i.startswith(("gpt-4o", "gpt-4.1", "gpt-5", "o3", "o4", "o1")) and "mini-tts" not in i]
    elif provider == "anthropic":
        ids = [m["id"] for m in data.get("data", [])]; vis = [i for i in ids if "claude-3-5-haiku" not in i or True]
    else:
        ids = [m["name"].split("/", 1)[-1] for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])
               and m["name"].split("/", 1)[-1].startswith("gemini") and "embedding" not in m["name"] and "tts" not in m["name"] and "image" not in m["name"]]
        vis = list(ids)
    return {"text": ids or STATIC_MODELS[provider]["text"], "vision": vis or STATIC_MODELS[provider]["vision"]}

def test_connection(provider, key=None, host=None, get=None):
    """(ok, message) for the Settings 'Test connection' button."""
    if provider == "ollama":
        import llm
        names = llm.OllamaClient(host or "http://localhost:11434", "").check()
        return (True, f"Ollama is running with {len(names)} model(s).") if names is not None else (False, "Ollama isn't running. Open the Ollama app.")
    key = key if key is not None else keystore.get(provider)
    if not key: return False, f"No API key set for {NAMES[provider]}."
    try:
        n = len(list_models(provider, key, get=get)["text"]); return True, f"Connected to {NAMES[provider]} ({n} models available)."
    except ProviderError as e:
        return False, str(e)

class FallbackClient:
    """Cloud first; on a cloud failure use the local Ollama model (if one is installed), and say so once."""
    def __init__(self, primary, local, log=print):
        self.primary, self.local, self.log, self._local_ok, self.used_fallback = primary, local, log, None, False
    def __getattr__(self, k): return getattr(self.primary, k)
    def _has_local(self):
        if self._local_ok is None:
            try:
                names = self.local.check() or []
                self._local_ok = any(n.split(":")[0] in (self.local.model.split(":")[0], self.local.text_model.split(":")[0]) for n in names)
            except Exception: self._local_ok = False
        return self._local_ok
    def _run(self, name, *a, **k):
        self.last_fallback = None
        try: return getattr(self.primary, name)(*a, **k)
        except ProviderError as e:
            if not self._has_local(): raise
            if not self.used_fallback: self.log(f"[model] {NAMES.get(self.primary.provider, self.primary.provider)} failed, using the local model: {e}")
            self.used_fallback = True; self.last_fallback = str(e)[:300]
            k.pop("model", None)
            return getattr(self.local, name)(*a, **k)
    def chat(self, *a, **k): return self._run("chat", *a, **k)
    def text_chat(self, *a, **k): return self._run("text_chat", *a, **k)
    def preload(self): pass
    def check(self): return self.primary.check()

def local_client(cfg):
    import llm
    o = cfg["ollama"]
    return llm.OllamaClient(o["host"], o["model"], o.get("fallback_model", ""), o.get("temperature", 0.1), o.get("timeout_s", 180),
                            text_model=o.get("text_model", ""), keep_alive=o.get("keep_alive", "30m"),
                            num_predict=o.get("num_predict", 200), num_ctx=o.get("num_ctx"))

def provider_name(cfg):
    return ((cfg.get("provider") or {}).get("name") or "ollama").lower()

def make_client(cfg, log=print, local_factory=None, key=None):
    """The model client for the configured provider (Local is the default)."""
    p = provider_name(cfg)
    local = (local_factory or local_client)(cfg)
    if p == "ollama": local.provider = "ollama"; return local
    pc = (cfg.get("provider") or {}); sub = pc.get(p) or {}
    cc = CloudClient(p, sub.get("text_model") or DEFAULTS[p]["text_model"], sub.get("vision_model") or DEFAULTS[p]["vision_model"],
                     key=key, timeout_s=pc.get("timeout_s", 60), retries=pc.get("retries", 2),
                     num_predict=cfg["ollama"].get("num_predict", 200), temperature=cfg["ollama"].get("temperature", 0.1))
    return FallbackClient(cc, local, log=log) if pc.get("fallback_local", True) else cc

def vision_model_name(cfg):
    p = provider_name(cfg)
    if p == "ollama": return cfg.get("ollama", {}).get("model", "")
    return ((cfg.get("provider") or {}).get(p) or {}).get("vision_model") or DEFAULTS[p]["vision_model"]

def norm_coords(cfg):
    """Vision coordinate convention: qwen3-vl and Gemini answer in 0-1000 normalized coords; GPT/Claude in image pixels."""
    mode = cfg.get("agent", {}).get("coord_mode", "auto")
    if mode != "auto": return mode == "norm1000"
    p = provider_name(cfg)
    if p == "gemini": return True
    if p in ("openai", "anthropic"): return False
    return "qwen3-vl" in vision_model_name(cfg).lower()


class TracingClient:
    """2.3.5: records provider / model / seconds / fallback (+ reason) for every LLM call -> on_event(dict). Never sees or logs keys."""
    def __init__(self, inner, on_event):
        self.inner, self.on_event = inner, on_event
    def __getattr__(self, k): return getattr(self.inner, k)
    def _who(self, kind, model):
        c = self.inner; base = getattr(c, "primary", c)
        prov = getattr(base, "provider", None) or "ollama"
        m = model or (getattr(base, "text_model", "") if kind == "text" else getattr(base, "model", "")) or getattr(base, "model", "")
        return prov, m
    def _call(self, kind, fn, *a, **k):
        prov, model = self._who(kind, k.get("model")); t = time.time(); err = None
        try: return fn(*a, **k)
        except Exception as e: err = f"{type(e).__name__}: {str(e)[:200]}"; raise
        finally:
            fb = getattr(self.inner, "last_fallback", None)
            ev = {"provider": prov, "model": model, "kind": kind, "secs": round(time.time() - t, 2), "fallback": bool(fb)}
            if fb:
                loc = getattr(self.inner, "local", None)
                ev.update(fallback_reason=fb, used="ollama", used_model=(getattr(loc, "text_model", "") if kind == "text" else getattr(loc, "model", "")) if loc else "")
            if err: ev["error"] = err
            try: self.on_event(ev)
            except Exception: pass
    def chat(self, *a, **k): return self._call("vision", self.inner.chat, *a, **k)
    def text_chat(self, *a, **k): return self._call("text", self.inner.text_chat, *a, **k)
