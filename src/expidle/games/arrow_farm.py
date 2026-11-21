"""Play a fixed number of expert boards with guarded reward-button taps."""
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import median
from time import monotonic, sleep

from PIL import Image

from ..core import Point, RecognitionError, Screen, ToolkitError, execute
from .arrow import Board
from .arrow_screen import ArrowPuzzle

Box = tuple[int, int, int, int]
REWARD_DELAY = 0.15
PACE_INTERVAL = 10


def mask(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    background = round(median(gray.get_flattened_data()))
    return gray.point(lambda value: 255 if abs(value - background) >= 52 else 0, "1")


@dataclass(frozen=True)
class Marker:
    box: Box
    bits: int
    shift: int

    @classmethod
    def from_frame(cls, frame: Image.Image, box: Box, shift: int) -> "Marker":
        left, top, right, bottom = box
        if not (0 <= left - shift < right + shift <= frame.width and 0 <= top < bottom <= frame.height):
            raise ToolkitError("Button text box extends outside the screenshot.")
        bits = int.from_bytes(mask(frame.crop(box)).tobytes(), "big")
        if not bits or bits.bit_count() < 0.015 * (right - left) * (bottom - top):
            raise ToolkitError("Select a tight rectangle around visible button text.")
        return cls(box, bits, shift)

    def matches(self, frame: Image.Image) -> bool:
        left, top, right, bottom = self.box
        search = mask(frame.crop((left - self.shift, top, right + self.shift, bottom)))
        width = right - left
        for x in range(2 * self.shift + 1):
            part = search.crop((x, 0, x + width, bottom - top))
            bits = int.from_bytes(part.tobytes(), "big")
            distance = (bits ^ self.bits).bit_count() / (bits.bit_count() + self.bits.bit_count())
            if distance <= 0.16:
                return True
        return False


@dataclass(frozen=True)
class FarmProfile:
    size: tuple[int, int]
    active: Marker
    reward: Marker

    @property
    def reward_point(self) -> Point:
        left, top, right, bottom = self.reward.box
        return (left + right) // 2, (top + bottom) // 2

    def matches(self, frame: Image.Image, *, solved: bool) -> bool:
        expected, other = (self.reward, self.active) if solved else (self.active, self.reward)
        return frame.size == self.size and expected.matches(frame) and not other.matches(frame)

    @classmethod
    def create(
        cls, puzzle: ArrowPuzzle, active: Image.Image, solved: Image.Image, active_box: Box, reward_box: Box,
    ) -> "FarmProfile":
        if puzzle.profile.difficulty != "expert":
            raise ToolkitError("Farm mode requires an expert board profile.")
        if puzzle.solved(puzzle.read(active)) or not puzzle.solved(puzzle.read(solved)):
            raise ToolkitError("Provide one active expert board and one solved expert board.")
        result = cls(
            active.size, Marker.from_frame(active, active_box, 0),
            Marker.from_frame(solved, reward_box, round(solved.width * 0.04)),
        )
        if not result.matches(active, solved=False) or not result.matches(solved, solved=True):
            raise ToolkitError("The two button labels could not be distinguished.")
        if any(y >= min(active_box[1], reward_box[1]) for _, y in puzzle.points):
            raise ToolkitError("Select the button text below the board.")
        return result

    @classmethod
    def load(cls, path: Path) -> "FarmProfile":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["format"] != 1:
                raise ValueError("unsupported format")
            width, height = data["size"]
            markers = []
            for key in ("active", "reward"):
                values = data[key]
                left, top, right, bottom = values["box"]
                bits = int(values["bits"], 16)
                shift = values["shift"]
                if (not 0 <= shift <= width // 20 or bits <= 0
                        or not 0 <= left - shift < right + shift <= width or not 0 <= top < bottom <= height
                        or bits.bit_length() > ((right - left + 7) // 8) * (bottom - top) * 8):
                    raise ValueError(f"invalid {key} marker")
                markers.append(Marker((left, top, right, bottom), bits, shift))
            return cls((width, height), *markers)
        except (ValueError, TypeError, KeyError, OSError) as error:
            raise ToolkitError(f"Invalid farm profile {path}: {error}") from error

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"format": 1, "size": self.size}
        for key, marker in (("active", self.active), ("reward", self.reward)):
            data[key] = {"box": marker.box, "bits": format(marker.bits, "x"), "shift": marker.shift}
        with path.open("x", encoding="utf-8") as output:
            json.dump(data, output, indent=2)
            output.write("\n")


def current_board(frame: Image.Image, puzzle: ArrowPuzzle, profile: FarmProfile) -> Board:
    board = puzzle.read(frame)
    if not profile.matches(frame, solved=puzzle.solved(board)):
        raise RecognitionError("Cannot distinguish the active board from the reward screen.")
    return board


def wait_for_board(screen: Screen, puzzle: ArrowPuzzle, profile: FarmProfile, *, solved: bool) -> Board:
    deadline = monotonic() + 4
    while True:
        try:
            board = current_board(screen.capture(), puzzle, profile)
            if puzzle.solved(board) == solved:
                return board
        except RecognitionError:
            pass
        if monotonic() >= deadline:
            raise ToolkitError(f"Could not verify the {'reward screen' if solved else 'next board'}.")
        sleep(0.15)


def farm(
    screen: Screen, puzzle: ArrowPuzzle, profile: FarmProfile, rounds: int, batch_size: int | None, *,
    report=print,
) -> None:
    if puzzle.profile.difficulty != "expert" or profile.size != puzzle.profile.size:
        raise ToolkitError("Use matching expert board and farm profiles.")
    if rounds < 1 or (batch_size is not None and not 1 <= batch_size <= 12):
        raise ValueError("Invalid round count or batch size.")
    started_at = monotonic()
    processed = 0
    try:
        board = current_board(screen.capture(), puzzle, profile)
        if puzzle.solved(board):
            # A solved board already on screen can be used to start, but is not counted.
            screen.tap_many([profile.reward_point])
            board = wait_for_board(screen, puzzle, profile, solved=False)

        for number in range(1, rounds + 1):
            moves = puzzle.plan(board)
            report(f"Round {number}/{rounds}: {len(moves)} taps")
            if batch_size is None:
                screen.tap_many([move.point for move in moves])
            else:
                if not execute(screen, puzzle, board, moves, lambda *_: True, batch_size=batch_size):
                    raise ToolkitError("Board did not finish.")
                wait_for_board(screen, puzzle, profile, solved=True)
            processed += 1
            if batch_size is not None:
                report(f"Verified {processed}/{rounds} rounds.")
            if processed % PACE_INTERVAL == 0:
                elapsed = monotonic() - started_at
                if elapsed > 0:
                    report(
                        f"Pace after {processed} rounds: "
                        f"{elapsed / processed:.2f} s/round, "
                        f"{60 * processed / elapsed:.1f} rounds/min (run average)."
                    )
            if number < rounds:
                if batch_size is None:
                    sleep(REWARD_DELAY)
                screen.tap_many([profile.reward_point])
                board = wait_for_board(screen, puzzle, profile, solved=False)
        if batch_size is None:
            report(f"Sent solutions for {processed}/{rounds} rounds. Final board was not checked.")
    except ToolkitError as error:
        stage = "Sent solutions for" if batch_size is None else "Verified"
        raise ToolkitError(f"{stage} {processed}/{rounds} rounds. {error}") from error
