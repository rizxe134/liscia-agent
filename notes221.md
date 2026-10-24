## Liscia Agent 2.2.1

Fixes the "max steps reached" failure when you said "do it on google chrome".

- **A browser name is never treated as a site.** "chrome", "google chrome", "safari", "the browser" and similar names now set which browser to use. They are no longer used as a site or a search query.
- **"do it on chrome" redoes your previous request in Chrome.** For example, "open up linkedin then open up instagram on another tab" followed by "do it on google chrome" opens LinkedIn, then Instagram in a new tab.
- **Questions and lists are answered in the chat.** Requests like "top 10 most powerful armies" are searched, the results are read, and the answer appears in the chat. They no longer just open a site.
- **No more made-up clicks.** Actions that use element ids not on the current page are rejected, and the model is shown the real ids. A click or type that gets no response counts as a failure.
- **Clearer messages when it can't finish.** Instead of "max steps reached", it tells you what it tried, where it stopped, and what to try next. For a question, it first tries to answer from the page it has read.
- **Fixed typos:** linkden, linkdin, instagarm and similar misspellings are now understood.

### Download
| Platform | File |
|---|---|
| macOS (Apple Silicon) | `Liscia-Agent-2.2.1-macos-arm64.dmg` |
| Windows (x64) | `Liscia-Agent-2.2.1-windows-x64.zip` |
| Chrome extension | `liscia-agent-chrome-extension-2.2.1.zip` (required for the cursor and banner) |

### Install
- **macOS:** open the dmg and drag **Liscia Agent** to Applications, replacing the old one.
- **Windows:** quit Liscia Agent, unzip, and replace the contents of `%LOCALAPPDATA%\Programs\Liscia Agent`.
- **Extension:** unzip it (or update your unpacked folder), open `chrome://extensions`, then click **Reload** on Liscia Agent. (From 2.2.0 on, Liscia Agent can reload the extension itself.)
