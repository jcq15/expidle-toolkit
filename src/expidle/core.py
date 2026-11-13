"""Shared screen and execution contracts for minigames."""
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import monotonic, sleep
from typing import Protocol, TypeVar

from PIL import Image

State = TypeVar("State")
Point = tuple[int, int]


class ToolkitError(Exception):
    pass


class RecognitionError(ToolkitError):
    pass


class Screen(Protocol):
    def capture(self) -> Image.Image: ...
    def tap_many(self, points: Sequence[Point]) -> None: ...


@dataclass(frozen=True)
class Move:
    cell: int
    point: Point


class Puzzle(Protocol[State]):
    def read(self, frame: Image.Image) -> State: ...
    def plan(self, state: State) -> Sequence[Move]: ...
    def predict(self, state: State, move: Move) -> State: ...
    def solved(self, state: State) -> bool: ...


def execute(
    screen: Screen,
    puzzle: Puzzle[State],
    state: State,
    moves: Sequence[Move],
    approve: Callable[[Move, int], bool],
    *,
    timeout: float = 3.0,
    interval: float = 0.12,
    limit: int | None = None,
    batch_size: int = 1,
) -> bool:
    """Verify every batch against a fresh frame, without retrying input."""
    if batch_size < 1:
        raise ValueError("Batch size must be positive.")
    planned = moves[:limit]
    if not planned:
        return puzzle.solved(state)
    for start in range(0, len(planned), batch_size):
        batch = planned[start:start + batch_size]
        if not approve(batch[0], start + 1):
            break
        if puzzle.read(screen.capture()) != state:
            raise ToolkitError(f"Board changed before tap {start + 1}. Stopped.")
        expected = state
        for move in batch:
            expected = puzzle.predict(expected, move)
        screen.tap_many([move.point for move in batch])
        deadline = monotonic() + timeout
        # While the game is animating a batch, a readable frame can still be intermediate.
        while True:
            sleep(interval)
            try:
                observed = puzzle.read(screen.capture())
            except RecognitionError:
                observed = None
            if observed == expected:
                state = expected
                break
            if monotonic() >= deadline:
                raise ToolkitError(
                    f"Could not verify taps {start + 1}-{start + len(batch)}. Stopped without retrying."
                )
        if puzzle.solved(state):
            return True
    return puzzle.solved(state)
