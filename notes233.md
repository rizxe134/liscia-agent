## Liscia Agent 2.3.3

- **Everyday words no longer open apps.** "find me the latest news" used to open the macOS **News** app because the word "news" matched its name. Apps whose names are common words now open only when you clearly mean the app: "open News", "the News app", "in the Music app". This covers News, Music, Photos, Mail, Maps, Notes, Calendar, Weather, Books, Stocks, Clock, Files, Messages, Reminders, Calculator, Settings, TV, Home and others. Brand names still work as before ("play lofi on Spotify", "message Bob on Discord").
- **Naming a site or search engine keeps the task on the web.** "on google…", "on youtube…", "search…" or "website" keeps the request in the browser unless you also clearly name an app.
- **It no longer types your whole sentence into an app.** In an app, it types only the search term, never your full request.
- **Multi-step requests run every step.** "find the latest news… then open YouTube and find a good Hindi song" runs each step in turn. One failed step doesn't stop the others, and the reply shows a result for each step.
- **"you didn't do the rest" finishes the rest.** The chat remembers which steps finished, and this follow-up runs only the unfinished ones. Before, it just repeated one step.
- **"4 different news" gives you 4 stories.** Numbers like "4 different news", "5 headlines" or "three stories" set how many items you get. News questions use Google's News results, and each story comes with its outlet, from different outlets where possible.

### Download
| Platform | File |
|---|---|
| macOS (Apple Silicon) | `Liscia-Agent-2.3.3-macos-arm64.dmg` |
| Windows (x64) | `Liscia-Agent-2.3.3-windows-x64.zip` |
| Chrome extension | `liscia-agent-chrome-extension-2.3.3.zip` |

### Install
- **macOS:** open the dmg and drag **Liscia Agent** to Applications, replacing the old one.
- **Windows:** quit Liscia Agent, unzip, and replace the contents of `%LOCALAPPDATA%\Programs\Liscia Agent`.
- **Extension:** unzip it over your unpacked extension folder. On 2.2.0 or later it reloads itself when the app starts; otherwise click **Reload** in `chrome://extensions`.
