## Liscia Agent 2.3.8

### Fixed
- **Sidebar buttons draw correctly on macOS.** `[ + NEW CHAT ]`, RENAME, DELETE, SETTINGS and STOP now draw a clean border at every font size (10–22) and in every theme. Before, the border was offset and the corners were cut off.
- **NEW CHAT no longer creates a pile of empty chats.** If an untouched "New chat" already exists, it is reused.
- **"Summarize the top 5 articles" now uses the stories from the previous answer.** Each article is opened and read, and you get a 2–3 sentence summary with the outlet and link. It no longer runs a new search. If a page is paywalled or blocked, the agent says so and shows only the headline.
- **Cleaner news headlines.**
  - Outlet names stuck to the headline are removed ("Magazine", "WSJ", "The Seattle Times" and similar).
  - Snippet text at the end of a headline is cut off.
  - Outlet names read properly ("Chicago Tribune" instead of "Chicagotribune").
  - Items that aren't news, such as "headlines for school assembly", podcasts and audio briefings, are skipped.
- **News searches no longer add the year.** "Right now" means the latest news, so the query isn't pinned to "2026".

### New: terminal-style chat input
- **Up / Down:** go through the messages you've sent, newest first. Down past the newest message brings back your unsent draft.
- History is kept per chat plus a global list. It is saved across restarts (up to 500 entries each).
- **Ctrl+R:** reverse search through history. Press it again for an older match.
- **Esc:** clear the input box.
- **Ctrl+L:** clear the screen. The chat itself is kept.
- **Tab:** complete slash commands (`/to` → `/token`).

### Download
| File | For |
|---|---|
| `Liscia-Agent-2.3.8-mac.dmg` | macOS |
| `Liscia-Agent-2.3.8-windows.zip` | Windows |
| `Liscia-Agent-Extension-2.3.8.zip` | Chrome extension |

### Install
- **Mac:** open the dmg and drag Liscia Agent into Applications, replacing the old one. The app keeps its keychain access because the signature is stable.
- **Windows:** unzip and replace the old folder.
- **Extension:** the app reloads it automatically. You can also unzip the extension over your extension folder and click Reload in chrome://extensions.
