## Liscia Agent 2.3.1

- **"…then in a new tab open up xbox" now opens it.** A site named with "in a new tab" or "on a new tab" is treated as a website and opened in a new tab, even when it is not in the built-in site list. In 2.3.0 that last part of a multi-part request was left undone.
- **Follow-ups keep the list length.** "you didn't go to an article" after "find me an article of the top 10 …" now opens an article and still gives all 10, not 5.

### Download more local models (Settings → DOWNLOAD MODELS)
- A list of recommended Ollama models, each showing its download size, how much RAM it needs, and whether it handles text, images (vision), or both. Models too big for this computer's RAM are marked.
- A box for any other Ollama model name.
- Download with a progress bar and a Cancel button. Installed models are listed with Delete.
- Downloaded models show up in the text and vision model lists on the MODELS tab.
- A **HOW TO** dropdown explains the steps, the RAM guidance, and the manual `ollama pull <name>` command.

### A livelier agent cursor
- The cursor now moves for every action. It glides to what it's looking for, follows the lines it's reading, travels down the page while scrolling, and walks across a field while typing.
- While the model thinks, it drifts over the area being read and toward the next likely target.
- It's lightweight: one timer and smooth CSS movement. It still can't be clicked, never appears in page snapshots, and moves less if your system has reduced motion turned on.
- An older 2.2.x extension now reloads itself once when this version of the app starts, so updated extension files take effect without clicking Reload.

### Download
| Platform | File |
|---|---|
| macOS (Apple Silicon) | `Liscia-Agent-2.3.1-macos-arm64.dmg` |
| Windows (x64) | `Liscia-Agent-2.3.1-windows-x64.zip` |
| Chrome extension | `liscia-agent-chrome-extension-2.3.1.zip` |

### Install
- **macOS:** open the dmg and drag **Liscia Agent** to Applications, replacing the old one.
- **Windows:** quit Liscia Agent, unzip, and replace the contents of `%LOCALAPPDATA%\Programs\Liscia Agent`.
- **Extension:** unzip it over your unpacked extension folder. If you're on 2.2.0 or later, it reloads itself when the app starts. Otherwise click **Reload** on Liscia Agent in `chrome://extensions`.
