#!/usr/bin/env python3
"""Claude Computer Use — native macOS harness for Claude Sonnet 4.6.

Run interactively or with a one-shot prompt:

    python main.py                          # interactive REPL
    python main.py "Open Safari and go to example.com"
    python main.py --no-thinking "Take a screenshot"
"""

import argparse
import json
import os
import sys
import textwrap

from dotenv import load_dotenv
import anthropic

load_dotenv()

from tools import (
    ScreenInfo,
    execute_bash,
    execute_computer_action,
    execute_editor,
)

# ── Defaults ─────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-6"
TOOL_VERSION = "20251124"
BETA_FLAG = "computer-use-2025-11-24"
MAX_TOKENS = 16384
THINKING_BUDGET = 10240
MAX_ITERATIONS = 50

SYSTEM_PROMPT = textwrap.dedent("""\
    You are controlling a real macOS computer directly (not a VM).
    After each action, take a screenshot to verify the result before proceeding.
    If an action did not produce the expected result, re-examine the screen and retry.
    Use keyboard shortcuts when possible — they are more reliable than mouse clicks
    for menus and common operations.
    Be careful: this is a real machine. Do not delete important files, change system
    settings, or perform destructive operations unless explicitly asked.
""")


# ── Tool wiring ──────────────────────────────────────────────────────────────

def _build_tools(screen: ScreenInfo) -> list[dict]:
    return [
        {
            "type": f"computer_{TOOL_VERSION}",
            "name": "computer",
            "display_width_px": screen.api_width,
            "display_height_px": screen.api_height,
            "enable_zoom": True,
        },
        {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
        {"type": "bash_20250124", "name": "bash"},
    ]


def _handle_tool_call(block, screen: ScreenInfo) -> dict:
    name = block.name
    inp = block.input

    if name == "computer":
        content = execute_computer_action(inp, screen)
        return {"type": "tool_result", "tool_use_id": block.id, "content": content}

    if name == "bash":
        output = execute_bash(inp.get("command", ""), inp.get("restart", False))
        return {"type": "tool_result", "tool_use_id": block.id, "content": output}

    if name == "str_replace_based_edit_tool":
        output = execute_editor(inp)
        return {"type": "tool_result", "tool_use_id": block.id, "content": output}

    return {
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": f"Unknown tool: {name}",
        "is_error": True,
    }


# ── Pretty-printing ─────────────────────────────────────────────────────────

_BLUE = "\033[94m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _print_block(block) -> None:
    if block.type == "text":
        print(f"\n{_GREEN}{block.text}{_RESET}")
    elif block.type == "thinking":
        snippet = (block.thinking or "")[:300]
        if snippet:
            print(f"\n{_DIM}[thinking] {snippet}{'...' if len(block.thinking or '') > 300 else ''}{_RESET}")
    elif block.type == "tool_use":
        summary = json.dumps(block.input, indent=2)
        if len(summary) > 400:
            summary = summary[:400] + "\n  ..."
        print(f"\n{_YELLOW}[{block.name}]{_RESET} {summary}")


def _print_usage(response) -> None:
    u = response.usage
    print(
        f"{_DIM}  tokens: {u.input_tokens:,} in / {u.output_tokens:,} out{_RESET}"
    )


# ── Agent loop ───────────────────────────────────────────────────────────────

def agent_loop(
    prompt: str,
    *,
    screen: ScreenInfo,
    system_prompt: str = SYSTEM_PROMPT,
    model: str = MODEL,
    max_iterations: int = MAX_ITERATIONS,
    thinking_budget: int = THINKING_BUDGET,
) -> list[dict]:
    client = anthropic.Anthropic()
    tools = _build_tools(screen)
    messages: list[dict] = [{"role": "user", "content": prompt}]
    total_input = 0
    total_output = 0

    print(f"\n{'=' * 60}")
    print(f"  Model   : {model}")
    print(f"  Display : {screen.logical_width}x{screen.logical_height} logical  "
          f"({screen.physical_width}x{screen.physical_height} physical)")
    print(f"  API res : {screen.api_width}x{screen.api_height}")
    print(f"  Thinking: {'off' if thinking_budget <= 0 else f'{thinking_budget:,} tokens'}")
    print(f"{'=' * 60}")

    for iteration in range(1, max_iterations + 1):
        print(f"\n{_BLUE}--- iteration {iteration}/{max_iterations} ---{_RESET}")

        kwargs: dict = dict(
            model=model,
            max_tokens=MAX_TOKENS,
            messages=messages,
            tools=tools,
            betas=[BETA_FLAG],
        )
        if thinking_budget > 0:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        if system_prompt:
            kwargs["system"] = system_prompt

        response = client.beta.messages.create(**kwargs)

        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens
        _print_usage(response)

        for block in response.content:
            _print_block(block)

        messages.append({"role": "assistant", "content": response.content})

        # Execute any tool calls
        tool_results: list[dict] = []
        for block in response.content:
            if block.type == "tool_use":
                try:
                    result = _handle_tool_call(block, screen)
                except Exception as e:
                    print(f"\n{_YELLOW}  error executing {block.name}: {e}{_RESET}")
                    result = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {e}",
                        "is_error": True,
                    }
                tool_results.append(result)

        if not tool_results:
            print(f"\n{_GREEN}--- task complete ---{_RESET}")
            print(f"{_DIM}  total tokens: {total_input:,} in / {total_output:,} out{_RESET}")
            break

        messages.append({"role": "user", "content": tool_results})
    else:
        print(f"\n{_YELLOW}--- reached max iterations ({max_iterations}) ---{_RESET}")
        print(f"{_DIM}  total tokens: {total_input:,} in / {total_output:,} out{_RESET}")

    return messages


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claude Computer Use — native macOS harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "prompt", nargs="?", help="One-shot task prompt (omit for interactive mode)"
    )
    parser.add_argument("--model", default=MODEL, help=f"Model ID (default: {MODEL})")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=MAX_ITERATIONS,
        help=f"Max agent-loop iterations (default: {MAX_ITERATIONS})",
    )
    parser.add_argument(
        "--thinking-budget",
        type=int,
        default=THINKING_BUDGET,
        help=f"Extended-thinking token budget (default: {THINKING_BUDGET})",
    )
    parser.add_argument(
        "--no-thinking", action="store_true", help="Disable extended thinking"
    )
    parser.add_argument("--system-prompt", default=SYSTEM_PROMPT, help="System prompt")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: set the ANTHROPIC_API_KEY environment variable.", file=sys.stderr)
        sys.exit(1)

    screen = ScreenInfo.detect()
    thinking_budget = 0 if args.no_thinking else args.thinking_budget

    if args.prompt:
        agent_loop(
            args.prompt,
            screen=screen,
            system_prompt=args.system_prompt,
            model=args.model,
            max_iterations=args.max_iterations,
            thinking_budget=thinking_budget,
        )
        return

    # Interactive REPL
    print(f"{_GREEN}Claude Computer Use — macOS Harness{_RESET}")
    print(f"Model   : {args.model}")
    print(f"Display : {screen.logical_width}x{screen.logical_height}")
    print("Type a task, or 'quit' to exit.\n")

    while True:
        try:
            prompt = input(f"{_BLUE}> {_RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if not prompt:
            continue
        if prompt.lower() in ("quit", "exit", "q"):
            break
        agent_loop(
            prompt,
            screen=screen,
            system_prompt=args.system_prompt,
            model=args.model,
            max_iterations=args.max_iterations,
            thinking_budget=thinking_budget,
        )


if __name__ == "__main__":
    main()
