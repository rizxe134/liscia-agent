## Liscia Agent 2.3.6

- **See which model answered.** The step log shows "via Google Gemini (model)" or "Google Gemini failed, using the local model: <reason>", for example quota exceeded (429) or model not found. Every model call is recorded in the run log with provider, model, time and whether it fell back to local, plus the reason. API keys are never logged.
- **Rule or model?** The step log says whether each plan was decided by a built-in rule or by the model.
- **Newer Gemini models give complete replies.** Gemini 3.x and "-latest" models think before answering, so they now get room for a full reply instead of coming back empty.

### Download
| Platform | File |
|---|---|
| macOS (Apple Silicon) | `Liscia-Agent-2.3.6-macos-arm64.dmg` |
| Windows (x64) | `Liscia-Agent-2.3.6-windows-x64.zip` |
| Chrome extension | `liscia-agent-chrome-extension-2.3.6.zip` |

### Install
- **macOS:** open the dmg and drag **Liscia Agent** to Applications, replacing the old one.
- **Windows:** quit Liscia Agent, unzip, and replace the contents of `%LOCALAPPDATA%\Programs\Liscia Agent`.
- **Extension:** unzip it over your unpacked extension folder. On 2.2.0 or later it reloads itself when the app starts; otherwise click **Reload** in `chrome://extensions`.
