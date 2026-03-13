# Claude Computer Use — macOS Harness

A native macOS harness that lets Claude Sonnet 4.6 see and control your desktop directly — no VM or Docker required.

## What it does

- **Screenshots** via `screencapture` with automatic Retina-aware downscaling
- **Mouse control** (click, double-click, right-click, drag, move) via `cliclick`
- **Keyboard input** (typing, key combos, modifier keys) via `cliclick`
- **Scrolling** via CoreGraphics events (JXA)
- **Zoom** for inspecting specific screen regions at full resolution
- **Bash** tool for running shell commands
- **Text editor** tool for viewing and editing files

## Prerequisites

- macOS 13+ (Ventura or later)
- Python 3.10+
- [`cliclick`](https://github.com/BlueM/cliclick) — install with `brew install cliclick`
- Accessibility permissions for your terminal app (System Settings → Privacy & Security → Accessibility)
- An [Anthropic API key](https://console.anthropic.com/)

## Setup

```bash
cd claude-computer-use
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Grant Accessibility Access

`cliclick` needs accessibility permissions to control mouse and keyboard.
Go to **System Settings → Privacy & Security → Accessibility** and enable the checkbox for your terminal app (Terminal.app, iTerm2, Cursor, etc.).

## Usage

### Interactive mode

```bash
python main.py
```

### One-shot prompt

```bash
python main.py "Open Safari, go to news.ycombinator.com, and take a screenshot"
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--model` | `claude-sonnet-4-6-20260217` | Anthropic model ID |
| `--thinking-budget` | `10240` | Extended-thinking token budget |
| `--no-thinking` | | Disable extended thinking |
| `--max-iterations` | `50` | Max agent-loop iterations |
| `--system-prompt` | *(built-in)* | Custom system prompt |

## How it works

1. Your prompt is sent to Claude along with the computer-use, bash, and text-editor tool definitions.
2. Claude decides which tool to call (e.g. `screenshot`, `left_click`, `type`).
3. The harness executes the action on your real macOS desktop and returns results.
4. Claude inspects the result and continues until the task is done.

### Coordinate scaling

Your Retina display's physical resolution is automatically detected and scaled to fit the API's image constraints (≤1568px longest edge, ≤1.15MP). Claude receives coordinates in the scaled space; the harness maps them back to logical screen coordinates for `cliclick`.

## Safety

This harness controls your **real computer**. Claude can click, type, and run shell commands. The built-in system prompt instructs it to be cautious, but you should:

- Watch what Claude is doing in real time
- Don't leave it running unattended on sensitive tasks
- Press Ctrl+C to stop the agent loop at any time
- Avoid giving it tasks near sensitive data or credentials
