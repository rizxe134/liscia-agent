"""Local slash commands for the chat app. Handled on this computer only: never sent to the model or written to run logs."""

HELP = """Slash commands:
  /token        show this install's key (token) and copy it to the clipboard
  /help         show this list
  /do <task>    force computer control for <task>
  /chat <msg>   force a plain chat reply (no computer control)
  /remember <x> save a note to this bot's memory   /memory  show it   /forget <word>  remove notes
  /bot          edit this bot   /newbot  create a bot   /trash  restore deleted bots"""

def handle(text, copy=None, token_loader=None):
    """Return the reply for a local command, or None if `text` isn't one (then it goes to the router as before)."""
    cmd = (text or "").strip().split(maxsplit=1)[0].lower() if (text or "").strip() else ""
    if cmd in ("/help", "/?", "/commands"):
        return HELP
    if cmd in ("/token", "/key"):
        if token_loader is None:
            import server; token_loader = server.load_token
        tok = token_loader()
        copied = False
        if copy:
            try: copy(tok); copied = True
            except Exception: copied = False
        return (f"Your key (token):\n  {tok}\n"
                "Paste it into the key box in the Liscia Agent Chrome panel (open the panel, then paste and save)."
                + ("\n(Copied to the clipboard.)" if copied else ""))
    return None

def is_local(text):
    t = (text or "").strip().lower()
    return t.split(maxsplit=1)[0] in ("/help", "/?", "/commands", "/token", "/key") if t else False
