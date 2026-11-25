# image-tools: a Claude Code plugin marketplace

This repository is a [Claude Code](https://docs.claude.com/en/docs/claude-code) plugin marketplace named **`image-tools`**. It contains one plugin, **`image-delegation`**.

## What `image-delegation` does

Some model servers accept only a limited number of images per request (default 8). Claude Code re-sends the whole history with every request, so that limit is also the lifetime image cap of a context, and one image too many fails the session with HTTP 400.

This plugin keeps the main agent at **0 images**:

- Screenshots, image files and PDF figures are viewed only by a **fresh `image-inspector` subagent** with an explicit `IMAGE_BUDGET`. The main agent gets back a text-only report.
- A **guard hook** enforces this. It blocks image Reads and screenshot tools in the main agent, and it counts images per subagent against the subagent's budget.
- A **skill** teaches the workflow: text first, save files without opening them, batch them, and delegate the batches in parallel.
- **`imgtool`** handles preprocessing and prints text only: list/batch, info, resize, crop, tile, pdf-scan, pdf-text, pdf-render, and web screenshots via Playwright.

Details: [plugins/image-delegation/README.md](plugins/image-delegation/README.md)

## Requirements

- Claude Code with a vision-capable model
- `sh` (on Windows: [Git for Windows](https://git-scm.com/download/win) / Git Bash)
- Python 3.8+ with Pillow: `pip install pillow`
- Optional:
  - PDFs: poppler (`pdftotext`, `pdfimages`, `pdftoppm`) or `pip install pymupdf`
  - Web screenshots: `pip install playwright && playwright install chromium`, or Node.js for `npx playwright`
  - OCR: `tesseract`

At session start, the plugin tells Claude which dependencies are missing. Claude reports them to you and does not install anything.

## Install

| Scope | Where it is recorded | Who gets it |
|---|---|---|
| `user` (default) | `~/.claude/settings.json` | You, in every project |
| `project` | `<project>/.claude/settings.json` (committed) | Everyone who works in that project |
| `local` | `<project>/.claude/settings.local.json` (not committed) | Only you, only in that project |

### For yourself (user scope, all projects)

```sh
claude plugin marketplace add mixedsoc-maker/image-delegation
claude plugin install image-delegation@image-tools
```

You can also run these inside Claude Code: `/plugin marketplace add mixedsoc-maker/image-delegation`, then install it from `/plugin`.

### For a whole project team (project scope)

Run this from the project's root:

```sh
claude plugin marketplace add mixedsoc-maker/image-delegation --scope project
claude plugin install image-delegation@image-tools --scope project
```

Then commit `.claude/settings.json`. Teammates are offered the plugin when they trust the project folder. You can also write the settings by hand:

```json
{
  "extraKnownMarketplaces": {
    "image-tools": {
      "source": { "source": "github", "repo": "mixedsoc-maker/image-delegation" }
    }
  },
  "enabledPlugins": {
    "image-delegation@image-tools": true
  }
}
```

### Only for yourself in one project (local scope)

Run this from the project's root:

```sh
claude plugin marketplace add mixedsoc-maker/image-delegation --scope local
claude plugin install image-delegation@image-tools --scope local
```

This writes to `.claude/settings.local.json`, which is git-ignored, so teammates are not affected. Use it to try the plugin in one project before you enable it for the whole team with `--scope project`.

Restart Claude Code (or run `/reload-plugins`) after installing.

### Try it without installing

```sh
git clone https://github.com/mixedsoc-maker/image-delegation.git
claude --plugin-dir image-delegation/plugins/image-delegation
```

## Configure

| Option | Default | Meaning |
|---|---|---|
| `hard_limit` | 8 | Max images per request, which is also the lifetime cap of each context |
| `default_budget` | 6 | Image budget per inspector when a delegation states none. Keep it below `hard_limit`. |

Change them with `/plugin configure image-delegation@image-tools` or the `/config` panel, then restart Claude Code.

## Check that it works

- Dependency status: from a clone, run `sh plugins/image-delegation/scripts/imgtool.sh doctor`.
- Guard test (offline): `python plugins/image-delegation/tests/test_image_guard.py`
- End-to-end checks: see [plugins/image-delegation/tests/README.md](plugins/image-delegation/tests/README.md).

## Update

```sh
claude plugin marketplace update image-tools
```

Then update the plugin from `/plugin` and restart Claude Code.

## Uninstall

```sh
claude plugin uninstall image-delegation@image-tools
claude plugin marketplace remove image-tools
```

## Repository layout

```
.claude-plugin/marketplace.json        marketplace "image-tools"
plugins/image-delegation/
  .claude-plugin/plugin.json           plugin manifest and userConfig
  agents/image-inspector.md            vision subagent with an image budget
  skills/image-delegation/             workflow skill, reference and prompt template
  hooks/hooks.json                     SessionStart context and PreToolUse guard
  scripts/                             image_guard.py, imgtool, dependency check
  tests/                               offline tests, fixtures, transcript auditor
```

## Limitations

- Images pasted into the chat count against the main agent's limit, and nothing can block them.
- The guard detects screenshot tools by name and argument patterns. To cover other MCP servers, extend the patterns in `scripts/image_guard.py`.
- Some checks read Claude Code's internal transcript files, which may change between versions. The guard fails open on errors.

## License

MIT
