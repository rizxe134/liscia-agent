## Liscia Agent 2.3.4

- **Multi-step requests that mention YouTube now run every step.** In 2.3.3, "find the latest news in 4 different news stations then open YouTube and find a good Hindi song" was turned into one YouTube search for the whole sentence. Now each step runs on its own.
- **"4 different news stations" gives 4 of the latest stories.** It searches Google News for the latest news and returns 4 stories from different outlets, instead of stories about TV stations.

### Download
| Platform | File |
|---|---|
| macOS (Apple Silicon) | `Liscia-Agent-2.3.4-macos-arm64.dmg` |
| Windows (x64) | `Liscia-Agent-2.3.4-windows-x64.zip` |
| Chrome extension | `liscia-agent-chrome-extension-2.3.4.zip` |

### Install
- **macOS:** open the dmg and drag **Liscia Agent** to Applications, replacing the old one.
- **Windows:** quit Liscia Agent, unzip, and replace the contents of `%LOCALAPPDATA%\Programs\Liscia Agent`.
- **Extension:** unzip it over your unpacked extension folder. On 2.2.0 or later it reloads itself when the app starts; otherwise click **Reload** in `chrome://extensions`.
