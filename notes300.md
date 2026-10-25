## Liscia Agent 3.0.0 - Bots, Connections, MCP

### Every chat is now a bot
- Each bot in the sidebar has:
  - a name, a short description and its own animated pixel robot (pick a colour and style);
  - its own instructions/persona and its own chat history;
  - its own memory: say "remember that ...", or use `/remember`, `/memory` and `/forget`;
  - an optional model or provider of its own (the default is the global one);
  - the app connections and MCP servers it's allowed to use.
- **+ NEW BOT** starts from a template: General, Researcher, Music or Calendar.
- **PROFILE** opens a bot's info pane: instructions, model, tools, and its memory with a delete button for each note.
- **Status:** while a bot works, its robot shows a thinking animation and "working..." under its name. A ● dot appears when a bot replies while you're on another one.
- **Bots can ask each other.** Type `@Music what should I play?` and the Music bot answers in this chat with its own robot.
- **Who said what:** every reply shows the bot's robot and name; your messages are marked `you >`.
- **Your existing chats became bots**, with nothing lost. The chats folder is backed up once, before the conversion, to `backups/chats-pre-3.0.0-*` in the app data folder.
- **DELETE** asks first and moves the bot to **TRASH** for 30 days, where you can restore it.

### Settings → CONNECTIONS
- **Google (Calendar, Gmail, Drive).** Bots can list, create, update and delete events; search and read mail; create Gmail **drafts**; and search and read Drive files.
- **Microsoft 365.** Bots can use your Outlook calendar and mail, and create drafts.
- **Spotify.** Bots can play a song and control playback.
- **GitHub and Notion**, connected with a token you paste in.
- **Sign-in:** Google, Microsoft and Spotify use the standard browser sign-in. They need your own (free) app client; each provider's **How to set up** dropdown walks you through creating one.
- Tokens and client secrets are stored only in the OS keychain, never in config.yaml or logs.
- **Anything that creates, changes, deletes or posts shows an APPROVE / CANCEL card in the chat first.** Email is only ever drafted, never sent.

### Settings → MCP
- **Add an MCP server:**
  - a local command (stdio), or
  - a remote server (Streamable HTTP or SSE, with an optional auth token kept in the keychain).
- **Per server:** TEST + LIST TOOLS, VIEW LOG, and tick tools on or off. You can also limit which bots may use each server.
- **Built-in demo server** (date and time, list a folder, system info): try MCP with nothing else installed.
- **Filesystem example** (`npx @modelcontextprotocol/server-filesystem`). If Node.js is missing, you get a clear message saying so.
- **Read-only tools run directly.** Other tools ask before running, unless you tick "always allow" for that tool. The tool's arguments are checked against its schema before it runs.

### Also
- Robots idle with a gentle bob and an occasional blink, and do a small happy bounce when a task finishes.
- A "*Bot* is thinking · · ·" line shows in the chat while the bot works.
- The robots and the sidebar follow your theme and font size.
- Everything from 2.x still works: web, media, app control, safety checks, providers with fallback, input history, the step log.

### Download
| File | For |
|---|---|
| `Liscia-Agent-3.0.0-macos-arm64.dmg` | macOS (Apple Silicon) |
| `Liscia-Agent-3.0.0-windows-x64.zip` | Windows |
| `liscia-agent-chrome-extension-3.0.0.zip` | Chrome extension |

### Install
- **Mac:** open the dmg and drag Liscia Agent into Applications, replacing the old one. Keychain access is kept because the signature is stable.
- **Windows:** unzip and replace the old folder.
- **Extension:** the app reloads it automatically. You can also unzip it over your extension folder and click Reload in chrome://extensions.
