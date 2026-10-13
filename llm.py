"""Ollama client: vision model for screen steps, fast text model for chat/routing/planning.
Keeps models warm (keep_alive), caps output length (num_predict) and supports streaming."""
import base64, io, json, requests

class OllamaClient:
    def __init__(self, host, model, fallback_model="", temperature=0.1, timeout_s=180,
                 text_model="", keep_alive="30m", num_predict=200, num_ctx=None):
        self.host, self.model, self.fallback = host.rstrip("/"), model, fallback_model
        self.text_model = text_model or model
        self.temperature, self.timeout = temperature, timeout_s
        self.keep_alive, self.num_predict, self.num_ctx = keep_alive, num_predict, num_ctx

    def _post(self, payload, on_token=None):
        payload.setdefault("keep_alive", self.keep_alive)
        payload["think"] = False  # qwen3/thinking models: no hidden reasoning, much faster
        if not on_token:
            payload["stream"] = False
            r = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
            if r.status_code == 400 and "think" in r.text:  # model without thinking support
                payload.pop("think"); r = requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout)
            r.raise_for_status()
            return r.json()["message"]["content"]
        payload["stream"] = True
        out = []
        with requests.post(f"{self.host}/api/chat", json=payload, timeout=self.timeout, stream=True) as r:
            if r.status_code == 400:
                payload.pop("think", None); payload["stream"] = False
                return self._post(payload)
            r.raise_for_status()
            for line in r.iter_lines():
                if not line: continue
                chunk = json.loads(line)
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    out.append(piece); on_token(piece)
                if chunk.get("done"): break
        return "".join(out)

    def _chat(self, model, system, prompt, image, on_token=None):
        buf = io.BytesIO(); image.save(buf, format="PNG")
        payload = {"model": model, "format": "json",
                   "options": self._opts({"temperature": self.temperature, "num_predict": self.num_predict}),
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": prompt,
                                 "images": [base64.b64encode(buf.getvalue()).decode()]}]}
        return self._post(payload, on_token)

    def _opts(self, o):
        """Same num_ctx on every request (incl. preload) - a different value makes Ollama reload the model."""
        if self.num_ctx: o["num_ctx"] = self.num_ctx
        return o

    def chat(self, system, prompt, image, on_token=None):
        """Vision step. Returns the model's raw text (JSON expected)."""
        try:
            return self._chat(self.model, system, prompt, image, on_token)
        except Exception as e:
            if not self.fallback:
                raise
            print(f"[llm] {self.model} failed ({e}); trying fallback {self.fallback}")
            return self._chat(self.fallback, system, prompt, image, on_token)

    def text_chat(self, messages, json_mode=False, on_token=None, num_predict=None, model=None):
        """Text-only chat on the fast text model."""
        payload = {"model": model or self.text_model, "messages": messages,
                   "options": self._opts({"temperature": max(self.temperature, 0.3), "num_predict": num_predict or 512})}
        if json_mode: payload["format"] = "json"
        return self._post(payload, on_token)

    def preload(self):
        """Load models into memory now so the first real request is fast."""
        for m in dict.fromkeys([self.model, self.text_model]):
            try:
                requests.post(f"{self.host}/api/generate", json={"model": m, "keep_alive": self.keep_alive, "options": self._opts({})},
                              timeout=self.timeout)
            except Exception:
                pass

    def check(self):
        try:
            tags = requests.get(f"{self.host}/api/tags", timeout=5).json().get("models", [])
            return [m["name"] for m in tags]
        except Exception:
            return None
