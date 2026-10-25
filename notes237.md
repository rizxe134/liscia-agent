## Liscia Agent 2.3.7

- **No more repeated Keychain password prompts on Mac.** Mac builds are now signed with a stable local identity ("Liscia Agent Local Signing", bundle id `local.liscia.agent`). After you click **Always Allow** once, future updates keep that permission. Before, every build had a new signature, so macOS asked for your login password again.
- **The API key is read once per launch.** It is kept in memory rather than read from the Keychain on every request.

### Download
| Platform | File |
|---|---|
| macOS (Apple Silicon) | `Liscia-Agent-2.3.7-macos-arm64.dmg` |
| Windows (x64) | `Liscia-Agent-2.3.7-windows-x64.zip` |
| Chrome extension | `liscia-agent-chrome-extension-2.3.7.zip` |

### Install
- **macOS:** open the dmg and drag **Liscia Agent** to Applications, replacing the old one.
- **Windows:** quit Liscia Agent, unzip, and replace the contents of `%LOCALAPPDATA%\Programs\Liscia Agent`.
- **Extension:** unzip it over your unpacked extension folder. On 2.2.0 or later it reloads itself when the app starts; otherwise click **Reload** in `chrome://extensions`.
