## Liscia Agent 2.3.0

### Fixes from a review of recent runs
- **Complete answers to "top N" questions.** It reads about three times more of each page. If a list comes back shorter than you asked for (e.g. 5 of 10), it opens the best source article and finishes the list. It keeps the most complete answer it found, so a retry is no longer needed.
- **Asking for an article opens one.** "find me an article about…" or "you didn't go to an article" opens the best source article in Chrome, reads it, answers from it, and names the source. A site's actual article page is preferred over its home page.
- **"Try again" questions use the original question.** Follow-ups like "can you try again" are answered as the earlier question, not as the words "try again".
- **Multi-part requests are finished.** "search the top 10 fastest cars, then open GitHub in a new tab, then Xbox" answers the question and then opens the other sites in new tabs. Asking for a new tab means the browser, so the GitHub Desktop app is no longer opened instead.
- **Lists display cleanly.** Answers no longer show up as `['1. …', '2. …']`.
- **"Play the 5th video you see" picks by position.** It plays the 5th video on YouTube (or the 5th result for a topic), instead of searching for a video titled "5th video you".

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
| macOS (Apple Silicon) | `Liscia-Agent-2.3.0-macos-arm64.dmg` |
| Windows (x64) | `Liscia-Agent-2.3.0-windows-x64.zip` |
| Chrome extension | `liscia-agent-chrome-extension-2.3.0.zip` |

### Install
- **macOS:** open the dmg and drag **Liscia Agent** to Applications, replacing the old one.
- **Windows:** quit Liscia Agent, unzip, and replace the contents of `%LOCALAPPDATA%\Programs\Liscia Agent`.
- **Extension:** unzip it over your unpacked extension folder. If you're on 2.2.0 or later, it reloads itself when the app starts. Otherwise click **Reload** on Liscia Agent in `chrome://extensions`.
