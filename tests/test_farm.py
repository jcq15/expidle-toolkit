import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import ImageDraw, ImageFont

from expidle.core import ToolkitError
from expidle.games.arrow_farm import FarmProfile, farm
from expidle.games.arrow_screen import ArrowPuzzle, calibrate
from test_arrow import render


def frame_with_label(board, label):
    frame, bounds = render("expert", board)
    draw = ImageDraw.Draw(frame)
    draw.text((400, 850), label, anchor="mm", font=ImageFont.load_default(size=28))
    return frame, bounds


class FakeGame:
    def __init__(self, puzzle, boards):
        self.puzzle = puzzle
        self.boards = iter(boards)
        self.board = (0,) * 37
        self.advance_taps = 0
        self.reward_label = "Awarded 25 stars"

    def capture(self):
        label = self.reward_label if not any(self.board) else "Give up"
        return frame_with_label(self.board, label)[0]

    def tap_many(self, points):
        for point in points:
            if point not in self.puzzle.points:
                if any(self.board):
                    raise AssertionError("Unexpected navigation tap on active board")
                self.advance_taps += 1
                self.board = next(self.boards)
            else:
                self.board = self.puzzle.rules.turn(self.board, self.puzzle.points.index(point))


class FarmTest(unittest.TestCase):
    def setUp(self):
        seed = tuple(i % 6 for i in range(37))
        sample, bounds = frame_with_label(seed, "Give up")
        self.puzzle = ArrowPuzzle(calibrate(sample, "expert", bounds, {i: i + 1 for i in range(6)}))
        self.finished = (0,) * 37
        self.active = self.puzzle.rules.turn(self.finished, 18)
        self.profile = FarmProfile.create(
            self.puzzle, frame_with_label(self.active, "Give up")[0],
            frame_with_label(self.finished, "Awarded 25 stars")[0],
            (340, 830, 461, 875), (280, 830, 521, 875),
        )

    @patch("expidle.core.sleep")
    def test_two_rounds_from_reward_screen(self, _):
        other = self.puzzle.rules.turn(self.finished, 0)
        device = FakeGame(self.puzzle, [self.active, other])
        messages = []
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            path = Path(folder) / "farm.json"
            self.profile.save(path)
            farm(device, self.puzzle, FarmProfile.load(path), 2, 8, report=messages.append)
        self.assertEqual(device.advance_taps, 2)
        self.assertEqual(device.board, self.finished)
        self.assertEqual(messages[-1], "Verified 2/2 rounds.")

    def test_unknown_reward_screen_stops_without_input(self):
        device = FakeGame(self.puzzle, [])
        device.reward_label = "Give up"
        with self.assertRaisesRegex(ToolkitError, "Completed 0/2"):
            farm(device, self.puzzle, self.profile, 2, 8, report=lambda _: None)
        self.assertEqual(device.advance_taps, 0)


if __name__ == "__main__":
    unittest.main()
