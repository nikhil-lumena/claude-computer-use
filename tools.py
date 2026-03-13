"""macOS tool implementations for Claude Computer Use.

Provides screenshot capture, mouse/keyboard control, scrolling, zoom,
bash execution, and text editor operations — all native to macOS without
requiring a VM or Docker container.
"""

import base64
import io
import math
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass

from PIL import Image

MAX_LONG_EDGE = 1568
MAX_PIXELS = 1_150_000


@dataclass
class ScreenInfo:
    logical_width: int
    logical_height: int
    physical_width: int
    physical_height: int
    retina_scale: float
    api_scale: float
    api_width: int
    api_height: int

    @classmethod
    def detect(cls) -> "ScreenInfo":
        logical_w, logical_h = _get_logical_resolution()
        physical_w, physical_h = _get_physical_resolution()
        retina_scale = physical_w / logical_w
        api_scale = _compute_api_scale(logical_w, logical_h)
        api_w = int(logical_w * api_scale)
        api_h = int(logical_h * api_scale)

        return cls(
            logical_width=logical_w,
            logical_height=logical_h,
            physical_width=physical_w,
            physical_height=physical_h,
            retina_scale=retina_scale,
            api_scale=api_scale,
            api_width=api_w,
            api_height=api_h,
        )


def _get_logical_resolution() -> tuple[int, int]:
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Finder" to get bounds of window of desktop',
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        parts = result.stdout.strip().split(", ")
        return int(parts[2]), int(parts[3])
    except Exception:
        # Fallback: capture screenshot and assume 2x Retina
        pw, ph = _get_physical_resolution()
        return pw // 2, ph // 2


def _get_physical_resolution() -> tuple[int, int]:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        subprocess.run(
            ["screencapture", "-x", "-D", "1", tmp],
            check=True,
            timeout=10,
        )
        with Image.open(tmp) as img:
            return img.size
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _compute_api_scale(width: int, height: int) -> float:
    long_edge = max(width, height)
    total_pixels = width * height
    long_edge_scale = MAX_LONG_EDGE / long_edge
    total_pixels_scale = math.sqrt(MAX_PIXELS / total_pixels)
    return min(1.0, long_edge_scale, total_pixels_scale)


def _api_to_logical(screen: ScreenInfo, x: int, y: int) -> tuple[int, int]:
    return round(x / screen.api_scale), round(y / screen.api_scale)


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

def take_screenshot(screen: ScreenInfo) -> str:
    """Capture the main display, resize to API dimensions, return base64 PNG."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        subprocess.run(
            ["screencapture", "-x", "-D", "1", tmp],
            check=True,
            timeout=10,
        )
        with Image.open(tmp) as img:
            resized = img.resize(
                (screen.api_width, screen.api_height), Image.LANCZOS
            )
        buf = io.BytesIO()
        resized.save(buf, format="PNG", optimize=True)
        return base64.standard_b64encode(buf.getvalue()).decode()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def take_zoom_screenshot(screen: ScreenInfo, region: list[int]) -> str:
    """Capture a specific screen region at full resolution."""
    x1_api, y1_api, x2_api, y2_api = region
    x1_log, y1_log = _api_to_logical(screen, x1_api, y1_api)
    x2_log, y2_log = _api_to_logical(screen, x2_api, y2_api)

    # Physical pixel coordinates
    px1 = int(x1_log * screen.retina_scale)
    py1 = int(y1_log * screen.retina_scale)
    px2 = int(x2_log * screen.retina_scale)
    py2 = int(y2_log * screen.retina_scale)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    try:
        subprocess.run(
            ["screencapture", "-x", "-D", "1", tmp],
            check=True,
            timeout=10,
        )
        with Image.open(tmp) as img:
            cropped = img.crop((px1, py1, px2, py2))

        crop_w, crop_h = cropped.size
        scale = _compute_api_scale(crop_w, crop_h)
        if scale < 1.0:
            cropped = cropped.resize(
                (int(crop_w * scale), int(crop_h * scale)), Image.LANCZOS
            )

        buf = io.BytesIO()
        cropped.save(buf, format="PNG", optimize=True)
        return base64.standard_b64encode(buf.getvalue()).decode()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Key mapping
# ---------------------------------------------------------------------------

_KEY_MAP = {
    "return": "return",
    "enter": "return",
    "tab": "tab",
    "escape": "escape",
    "space": "space",
    "backspace": "delete",
    "delete": "fwd-delete",
    "up": "arrow-up",
    "down": "arrow-down",
    "left": "arrow-left",
    "right": "arrow-right",
    "page_up": "page-up",
    "pageup": "page-up",
    "page_down": "page-down",
    "pagedown": "page-down",
    "home": "home",
    "end": "end",
    **{f"f{i}": f"f{i}" for i in range(1, 17)},
}

_MODIFIER_MAP = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "super": "cmd",
    "cmd": "cmd",
    "command": "cmd",
    "meta": "cmd",
    "fn": "fn",
}


def _execute_key(key_combo: str) -> None:
    parts = [p.strip() for p in key_combo.split("+")]

    if len(parts) == 1:
        key = parts[0].lower()
        ck = _KEY_MAP.get(key)
        if ck:
            subprocess.run(["cliclick", f"kp:{ck}"], check=True)
        elif len(key) == 1:
            subprocess.run(["cliclick", f"t:{parts[0]}"], check=True)
        else:
            subprocess.run(["cliclick", f"kp:{key}"], check=True)
        return

    modifiers = []
    main_key = None
    for part in parts:
        lower = part.lower()
        if lower in _MODIFIER_MAP:
            modifiers.append(_MODIFIER_MAP[lower])
        else:
            main_key = part

    cmds = []
    if modifiers:
        cmds.append(f"kd:{','.join(modifiers)}")
    if main_key:
        ck = _KEY_MAP.get(main_key.lower())
        if ck:
            cmds.append(f"kp:{ck}")
        elif len(main_key) == 1:
            cmds.append(f"t:{main_key}")
        else:
            cmds.append(f"kp:{main_key.lower()}")
    if modifiers:
        cmds.append(f"ku:{','.join(modifiers)}")

    subprocess.run(["cliclick", *cmds], check=True)


# ---------------------------------------------------------------------------
# Scroll via CoreGraphics (JXA)
# ---------------------------------------------------------------------------

def _execute_scroll(
    screen: ScreenInfo, x: int, y: int, direction: str, amount: int
) -> None:
    lx, ly = _api_to_logical(screen, x, y)
    subprocess.run(["cliclick", f"m:{lx},{ly}"], check=True)
    time.sleep(0.05)

    # CoreGraphics scroll: positive dy = scroll up, negative = scroll down
    dy, dx = 0, 0
    if direction == "up":
        dy = amount
    elif direction == "down":
        dy = -amount
    elif direction == "left":
        dx = amount
    elif direction == "right":
        dx = -amount

    jxa = (
        'ObjC.import("CoreGraphics");'
        f"var e=$.CGEventCreateScrollWheelEvent(null,0,2,{dy},{dx});"
        "$.CGEventPost(0,e);$.CFRelease(e);"
    )
    subprocess.run(["osascript", "-l", "JavaScript", "-e", jxa], check=True)


# ---------------------------------------------------------------------------
# Computer tool dispatcher
# ---------------------------------------------------------------------------

def _image_result(data_b64: str) -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": data_b64},
    }


def _text_result(text: str) -> dict:
    return {"type": "text", "text": text}


def execute_computer_action(action_input: dict, screen: ScreenInfo) -> list[dict]:
    """Execute a computer-use action. Returns a list of content blocks."""
    action = action_input.get("action")
    coord = action_input.get("coordinate")

    if action == "screenshot":
        return [_image_result(take_screenshot(screen))]

    if action == "zoom":
        return [_image_result(take_zoom_screenshot(screen, action_input["region"]))]

    if action == "left_click":
        lx, ly = _api_to_logical(screen, *coord)
        subprocess.run(["cliclick", f"c:{lx},{ly}"], check=True)

    elif action == "right_click":
        lx, ly = _api_to_logical(screen, *coord)
        subprocess.run(["cliclick", f"rc:{lx},{ly}"], check=True)

    elif action == "double_click":
        lx, ly = _api_to_logical(screen, *coord)
        subprocess.run(["cliclick", f"dc:{lx},{ly}"], check=True)

    elif action == "triple_click":
        lx, ly = _api_to_logical(screen, *coord)
        subprocess.run(["cliclick", f"tc:{lx},{ly}"], check=True)

    elif action == "middle_click":
        lx, ly = _api_to_logical(screen, *coord)
        _middle_click_jxa(lx, ly)

    elif action == "mouse_move":
        lx, ly = _api_to_logical(screen, *coord)
        subprocess.run(["cliclick", f"m:{lx},{ly}"], check=True)

    elif action == "left_click_drag":
        start = action_input.get("start_coordinate", coord)
        end = action_input.get("coordinate")
        slx, sly = _api_to_logical(screen, *start)
        elx, ely = _api_to_logical(screen, *end)
        subprocess.run(
            ["cliclick", f"dd:{slx},{sly}", f"du:{elx},{ely}"], check=True
        )

    elif action == "left_mouse_down":
        lx, ly = _api_to_logical(screen, *coord)
        subprocess.run(["cliclick", f"dd:{lx},{ly}"], check=True)

    elif action == "left_mouse_up":
        lx, ly = _api_to_logical(screen, *coord)
        subprocess.run(["cliclick", f"du:{lx},{ly}"], check=True)

    elif action == "type":
        text = action_input.get("text", "")
        subprocess.run(["cliclick", f"t:{text}"], check=True)

    elif action == "key":
        _execute_key(action_input.get("key", ""))

    elif action == "scroll":
        x, y = coord or (0, 0)
        direction = action_input.get("direction", "down")
        amount = action_input.get("amount", 3)
        _execute_scroll(screen, x, y, direction, amount)

    elif action == "hold_key":
        key = action_input.get("key", "").lower()
        duration = action_input.get("duration", 1)
        ck = _MODIFIER_MAP.get(key) or _KEY_MAP.get(key, key)
        subprocess.run(["cliclick", f"kd:{ck}"], check=True)
        time.sleep(duration)
        subprocess.run(["cliclick", f"ku:{ck}"], check=True)

    elif action == "wait":
        time.sleep(action_input.get("duration", 1))

    else:
        return [_text_result(f"Unknown action: {action}")]

    return [_text_result(f"Action '{action}' executed.")]


def _middle_click_jxa(x: int, y: int) -> None:
    jxa = (
        'ObjC.import("CoreGraphics");'
        f"var p=$.CGPointMake({x},{y});"
        "var d=$.CGEventCreateMouseEvent(null,$.kCGEventOtherMouseDown,p,2);"
        "var u=$.CGEventCreateMouseEvent(null,$.kCGEventOtherMouseUp,p,2);"
        "$.CGEventPost(0,d);$.CGEventPost(0,u);"
        "$.CFRelease(d);$.CFRelease(u);"
    )
    subprocess.run(["osascript", "-l", "JavaScript", "-e", jxa], check=True)


# ---------------------------------------------------------------------------
# Bash tool
# ---------------------------------------------------------------------------

BASH_TIMEOUT = 120


def execute_bash(command: str, restart: bool = False) -> str:
    """Execute a bash command and return combined stdout + stderr."""
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=BASH_TIMEOUT,
        )
        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(result.stderr)
        if result.returncode != 0:
            parts.append(f"[exit code: {result.returncode}]")
        return "\n".join(parts) or "(no output)"
    except subprocess.TimeoutExpired:
        return f"[command timed out after {BASH_TIMEOUT}s]"
    except Exception as e:
        return f"[error: {e}]"


# ---------------------------------------------------------------------------
# Text editor tool
# ---------------------------------------------------------------------------

def execute_editor(input_data: dict) -> str:
    """Handle str_replace_editor tool calls."""
    command = input_data.get("command")
    path = input_data.get("path", "")

    if command == "view":
        return _editor_view(path, input_data.get("view_range"))

    if command == "create":
        return _editor_create(path, input_data.get("file_text", ""))

    if command == "str_replace":
        return _editor_str_replace(
            path, input_data.get("old_str", ""), input_data.get("new_str", "")
        )

    if command == "insert":
        return _editor_insert(
            path, input_data.get("insert_line", 0), input_data.get("new_str", "")
        )

    if command == "undo_edit":
        return "Undo is not supported in this harness."

    return f"Unknown editor command: {command}"


def _editor_view(path: str, view_range: list[int] | None) -> str:
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return f"File not found: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"

    offset = 0
    if view_range:
        start = max(1, view_range[0]) - 1
        end = view_range[1] if len(view_range) > 1 else len(lines)
        lines = lines[start:end]
        offset = start

    return "".join(f"{i + offset + 1:6d}\t{line}" for i, line in enumerate(lines))


def _editor_create(path: str, file_text: str) -> str:
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w") as f:
            f.write(file_text)
        return f"File created: {path}"
    except Exception as e:
        return f"Error creating {path}: {e}"


def _editor_str_replace(path: str, old_str: str, new_str: str) -> str:
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        return f"File not found: {path}"

    count = content.count(old_str)
    if count == 0:
        return f"old_str not found in {path}"
    if count > 1:
        return f"old_str found {count} times in {path} — must be unique."

    with open(path, "w") as f:
        f.write(content.replace(old_str, new_str, 1))
    return f"Replacement applied in {path}"


def _editor_insert(path: str, insert_line: int, new_str: str) -> str:
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return f"File not found: {path}"

    lines.insert(insert_line, new_str + "\n")
    with open(path, "w") as f:
        f.writelines(lines)
    return f"Inserted text at line {insert_line} in {path}"
