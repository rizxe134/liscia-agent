## Liscia Agent 2.3.5

- **Asking for a song plays it.** "find me a good Hindi song" or "look for the song Pursuit" now plays the best match, alone or as one step of a longer request. "search youtube for X" still only searches.
- **An honest "you didn't do the rest".** If a step only searched, it now finishes the job by playing the best match. If every step already ran, it lists what each step did and asks what to redo. It no longer runs a web search on your complaint.
- **News shows its outlet.** Each story is listed as "1. Headline (Outlet)", taken straight from Google News, with different outlets preferred.

### Download
| Platform | File |
|---|---|
| macOS (Apple Silicon) | `Liscia-Agent-2.3.5-macos-arm64.dmg` |
| Windows (x64) | `Liscia-Agent-2.3.5-windows-x64.zip` |
| Chrome extension | `liscia-agent-chrome-extension-2.3.5.zip` |

### Install
- **macOS:** open the dmg and drag **Liscia Agent** to Applications, replacing the old one.
- **Windows:** quit Liscia Agent, unzip, and replace the contents of `%LOCALAPPDATA%\Programs\Liscia Agent`.
- **Extension:** unzip it over your unpacked extension folder. On 2.2.0 or later it reloads itself when the app starts; otherwise click **Reload** in `chrome://extensions`.
