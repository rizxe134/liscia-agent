## Liscia Agent 2.3.9

### Fixed
- **Each article summary now matches its own article.** When summarizing articles, the agent waits until each article's page has actually loaded before reading it. Before, a slow page could cause one article's text to be summarized under the next headline.
- **Cleaner news headlines.**
  - Snippet text that Google cut off mid-word is removed ("…intensifies on Ta", "…physics Known f").
  - A name repeated from the snippet is removed ("…dissent Neha Bora").
  - Outlet names stuck to the front of a headline are removed, however they are spaced ("Irish Golfer Magazine …").
  - Trailing words like "on" or "of" left after the cut are removed.

### Download
| File | For |
|---|---|
| `Liscia-Agent-2.3.9-macos-arm64.dmg` | macOS (Apple Silicon) |
| `Liscia-Agent-2.3.9-windows-x64.zip` | Windows |
| `liscia-agent-chrome-extension-2.3.9.zip` | Chrome extension |

### Install
- **Mac:** open the dmg and drag Liscia Agent into Applications, replacing the old one. Keychain access is kept because the signature is stable.
- **Windows:** unzip and replace the old folder.
- **Extension:** the app reloads it automatically. You can also unzip it over your extension folder and click Reload in chrome://extensions.
