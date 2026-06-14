# claudemon

A macOS menu bar app that monitors your [Claude Code](https://claude.ai/code) usage in real time.

Tracks token consumption, cache hit rates, query history, active session state, and
rate-limit utilization — all from a floating dashboard that lives next to your clock.

<img width="499" height="1047" alt="image" src="https://github.com/user-attachments/assets/c55f93f9-24ef-440c-99d4-25cce71ecf22" />

## Requirements

- macOS 13+
- Python 3.11+
- [just](https://github.com/casey/just) (task runner)

## Download

Grab the latest prebuilt `.app` from the [releases page](https://github.com/csmcdermott/claudemon/releases).

Unzip and double-click to run. The first launch of an unsigned bundle requires right-click → Open to bypass Gatekeeper.

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
just build          # builds dist/claudemon.app
just install-app    # builds and copies to /Applications/claudemon.app
just release        # builds, zips, and publishes a GitHub release
```

## Configuration

Settings live in `~/.claudemon/config.json` and are created automatically on first run.

| Key | Default | Description |
|-----|---------|-------------|
| `task_gap_minutes` | `30` | Idle time in minutes used to separate adjacent tasks |
| `section_collapse_state` | `{}` | Collapsed/expanded state for each dashboard section |
| `section_order` | `[]` | Dashboard section order set by drag-to-reorder |

## Contributing

See [CONTRIBUTORS.md](CONTRIBUTORS.md).

## License

[MIT](LICENSE)
