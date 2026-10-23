"""Settings (2.0.0): provider + per-role models saved to config.yaml; API keys ONLY in the OS keychain."""
import copy, os, re
import yaml
import keystore, providers

KEYISH = re.compile(r"(api[_-]?key|secret|token|password)$", re.I)

def defaults(cfg):
    cfg.setdefault("provider", {})
    p = cfg["provider"]; p.setdefault("name", "ollama"); p.setdefault("fallback_local", True); p.setdefault("timeout_s", 60)
    for name, d in providers.DEFAULTS.items():
        p.setdefault(name, {}); p[name].setdefault("text_model", d["text_model"]); p[name].setdefault("vision_model", d["vision_model"])
    return cfg

def scrub(obj):
    """Remove anything key-like before writing (defence in depth: keys are never put in cfg in the first place)."""
    if isinstance(obj, dict): return {k: scrub(v) for k, v in obj.items() if not KEYISH.search(str(k))}
    if isinstance(obj, list): return [scrub(v) for v in obj]
    return obj

def save(cfg, path=None):
    if path is None:
        import paths; path = paths.config_path()
    data = scrub(copy.deepcopy(cfg))
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    for prov in keystore.PROVIDERS:  # never write a stored key, even by accident
        k = keystore.get(prov)
        if k and k in text: raise RuntimeError("refusing to write an API key to config.yaml")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: f.write(text)
    os.replace(tmp, path); return path

def apply(cfg, changes):
    """changes: {'provider': 'openai', 'text_model': ..., 'vision_model': ..., 'fallback_local': bool, 'keys': {prov: key}}.
    Updates cfg in place (keys go to the keychain) and returns cfg."""
    defaults(cfg)
    for prov, key in (changes.get("keys") or {}).items():
        if prov in keystore.PROVIDERS and key is not None: keystore.set(prov, key)
    prov = changes.get("provider", cfg["provider"]["name"])
    if prov not in providers.NAMES: raise ValueError(f"unknown provider {prov}")
    cfg["provider"]["name"] = prov
    if "fallback_local" in changes: cfg["provider"]["fallback_local"] = bool(changes["fallback_local"])
    tm, vm = changes.get("text_model"), changes.get("vision_model")
    if prov == "ollama":
        if tm: cfg["ollama"]["text_model"] = tm
        if vm: cfg["ollama"]["model"] = vm
    else:
        if tm: cfg["provider"][prov]["text_model"] = tm
        if vm: cfg["provider"][prov]["vision_model"] = vm
    return cfg

def summary(cfg):
    defaults(cfg); p = cfg["provider"]["name"]
    if p == "ollama": return f"Local (Ollama) · text {cfg['ollama'].get('text_model')} · vision {cfg['ollama'].get('model')}"
    return f"{providers.NAMES[p]} · text {cfg['provider'][p]['text_model']} · vision {cfg['provider'][p]['vision_model']}"
