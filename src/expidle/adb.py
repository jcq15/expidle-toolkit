"""ADB adapter. Screenshots and input share Android display coordinates."""
from collections.abc import Sequence
from io import BytesIO
import re
import subprocess

from PIL import Image

from .core import Point, ToolkitError

PACKAGE = "com.conicgames.exponentialidle"


def adb_call(adb: str, *args: str, timeout: float = 15) -> bytes:
    try:
        return subprocess.run(
            [adb, *args], capture_output=True, check=True, timeout=timeout
        ).stdout
    except FileNotFoundError as error:
        raise ToolkitError("ADB not found. Install Android SDK Platform Tools.") from error
    except subprocess.TimeoutExpired as error:
        raise ToolkitError("ADB timed out.") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors="replace").strip()
        raise ToolkitError(f"ADB failed: {detail or error.returncode}") from error


class Android:
    def __init__(self, adb: str = "adb", serial: str | None = None, *, tap_delay_ms: int = 0):
        if not 0 <= tap_delay_ms <= 1000:
            raise ValueError("Tap delay must be between 0 and 1000 ms.")
        self.adb = adb
        self.tap_delay_ms = tap_delay_ms
        self._input_command: str | None = None
        lines = adb_call(adb, "devices").decode(errors="replace").splitlines()
        devices = [line.split()[0] for line in lines if line.endswith("\tdevice")]
        if serial is None and len(devices) == 1:
            serial = devices[0]
        if serial not in devices:
            raise ToolkitError("Connect and authorize one device, or select it with --serial.")
        self.serial = serial

    def run(self, *args: str, timeout: float = 15) -> bytes:
        return adb_call(self.adb, "-s", self.serial, *args, timeout=timeout)

    def require_game(self) -> None:
        windows = self.run("shell", "dumpsys", "window").decode(errors="replace")
        focus = re.search(r"^\s*mCurrentFocus=(.*)$", windows, re.MULTILINE)
        if not focus or not re.search(r"\s" + re.escape(PACKAGE) + r"/", focus[1]):
            raise ToolkitError("Exponential Idle is not the foreground app. Stopped.")

    def capture(self) -> Image.Image:
        self.require_game()
        data = self.run("exec-out", "screencap", "-p")
        try:
            with Image.open(BytesIO(data)) as frame:
                if frame.format != "PNG":
                    raise ToolkitError("ADB did not return a PNG screenshot.")
                return frame.convert("RGB")
        except OSError as error:
            raise ToolkitError("Invalid ADB screenshot.") from error

    def tap_many(self, points: Sequence[Point]) -> None:
        if not points:
            return
        if self._input_command is None:
            try:
                services = self.run("shell", "cmd", "-l").decode(errors="replace")
            except ToolkitError:
                services = ""
            self._input_command = "cmd input" if "input" in map(str.strip, services.splitlines()) else "input"
        self.require_game()
        commands = [f"{self._input_command} tap {int(x)} {int(y)}" for x, y in points]
        delay = self.tap_delay_ms / 1000
        separator = f" && sleep {delay:.3f} && " if delay else " && "
        self.run("shell", separator.join(commands), timeout=15 + (0.6 + delay) * len(commands))
