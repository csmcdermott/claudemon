# claudemon

A macOS menu bar app that monitors your [Claude Code](https://claude.ai/code) usage in real time.

Tracks token consumption, cache hit rates, query history, active session state, and
rate-limit utilization — all from a floating dashboard that lives next to your clock.

## Requirements

- macOS 13+
- Python 3.11+
- [just](https://github.com/casey/just) (task runner)

## Install from source

```bash
git clone https://github.com/csmcdermott/claudemon.git
cd claudemon
just setup          # creates .venv and installs dependencies
just install-hooks  # install pre-commit + pre-push hooks
claudemon           # launch the app
```

The menu bar icon appears and starts monitoring `~/.claude/projects/` immediately.

## Build a standalone .app bundle

```bash
just build          # → dist/claudemon.app
just install-app    # build and copy to /Applications/claudemon.app
```

The first launch of an unsigned bundle requires right-click → Open to bypass Gatekeeper.

## Configuration

Settings are stored in `~/.claudemon/config.json` and created automatically on first run.

| Key | Default | Description |
|-----|---------|-------------|
| `task_gap_minutes` | `30` | Idle time (minutes) used to separate adjacent tasks |

## Contributing

See [CONTRIBUTORS.md](CONTRIBUTORS.md).

## License

[MIT](LICENSE)
