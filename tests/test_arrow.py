import itertools
import random
import unittest

from PIL import Image, ImageDraw, ImageFont

from expidle.core import RecognitionError, ToolkitError, execute
from expidle.games.arrow import RULES, solve
from expidle.games.arrow_screen import ArrowPuzzle, calibrate


def render(difficulty, board, offset=0):
    rules = RULES[difficulty]
    bounds = (130, 140, 670, 760)
    frame = Image.new("RGB", (800, 900), "#282828")
    draw = ImageDraw.Draw(frame)
    font = ImageFont.load_default(size=38)
    points, radius = rules.centers(bounds)
    for i, (x, y) in enumerate(points):
        background = ("#2e2e2e", "#404544", "#595659")[board[i] % 3]
        r = radius * 1.32
        draw.ellipse((x-r, y-r, x+r, y+r), fill=background, outline="#666666", width=2)
        draw.text((x + offset, y - offset), str(board[i]+1), font=font, anchor="mm", fill="#eeeeee")
    return frame, bounds


class ArrowRulesTest(unittest.TestCase):
    def test_neighbors(self):
        easy = RULES["easy"]
        self.assertEqual(easy.neighbors(0), (0, 1, 3, 4))
        self.assertEqual(len(easy.neighbors(4)), 9)
        expert = RULES["expert"]
        self.assertEqual(len(expert.cells), 37)
        self.assertEqual(len(expert.neighbors(0)), 4)
        self.assertEqual(len(expert.neighbors(18)), 7)

    def test_seeded_scrambles(self):
        rng = random.Random(17)
        for difficulty, rules in RULES.items():
            for _ in range(6):
                with self.subTest(difficulty=difficulty):
                    board = (0,) * len(rules.cells)
                    for _ in range(40):
                        cell = rng.randrange(len(board))
                        for _ in range(rules.modulus - 1):
                            board = rules.turn(board, cell)
                    answer = solve(rules, board)
                    self.assertLessEqual(sum(answer), 40)
                    for cell, count in enumerate(answer):
                        for _ in range(count):
                            board = rules.turn(board, cell)
                    self.assertFalse(any(board))

    def test_optimal_against_exhaustive_easy_solution(self):
        rules = RULES["easy"]
        known = (1, 0, 0, 0, 2, 0, 0, 1, 0)
        board = (0,) * 9
        for cell, count in enumerate(known):
            for _ in range((-count) % rules.modulus):
                board = rules.turn(board, cell)
        # Search all plans strictly shorter than the returned four taps.
        self.assertEqual(sum(solve(rules, board)), 4)
        for count in range(4):
            for taps in itertools.combinations_with_replacement(range(9), count):
                trial = board
                for cell in taps:
                    trial = rules.turn(trial, cell)
                self.assertTrue(any(trial))

    def test_unsatisfiable_expert_board(self):
        rules = RULES["expert"]
        with self.assertRaises(ToolkitError):
            solve(rules, (1,) + (0,) * 36)


class MockAndroid:
    def __init__(self, puzzle, board, apply=True):
        self.puzzle, self.board, self.apply = puzzle, board, apply
        self.taps = []
        self.captures = 0

    def capture(self):
        self.captures += 1
        return render(self.puzzle.profile.difficulty, self.board, offset=2)[0]

    def tap_many(self, points):
        for point in points:
            self.taps.append(point)
            if self.apply:
                self.board = self.puzzle.rules.turn(self.board, self.puzzle.points.index(point))


class ScreenTest(unittest.TestCase):
    def test_recognition_in_all_four_layouts(self):
        for difficulty, rules in RULES.items():
            with self.subTest(difficulty=difficulty):
                sample = tuple(i % rules.modulus for i in range(len(rules.cells)))
                frame, bounds = render(difficulty, sample)
                profile = calibrate(frame, difficulty, bounds, {i: i+1 for i in range(rules.modulus)})
                puzzle = ArrowPuzzle(profile)
                shifted = tuple((value + 1) % rules.modulus for value in reversed(sample))
                frame, _ = render(difficulty, shifted, offset=2)
                self.assertEqual(puzzle.read(frame), shifted)
                with self.assertRaises(RecognitionError):
                    puzzle.read(Image.new("RGB", frame.size, "black"))
                with self.assertRaises(RecognitionError):
                    puzzle.read(frame.transpose(Image.Transpose.ROTATE_90))

    def make_puzzle(self):
        difficulty = "easy"
        sample = (0, 1, 2, 3, 0, 1, 2, 3, 0)
        frame, bounds = render(difficulty, sample)
        puzzle = ArrowPuzzle(calibrate(frame, difficulty, bounds, {i: i + 1 for i in range(4)}))
        board = puzzle.rules.turn((0,) * 9, 4)
        return puzzle, board

    def test_end_to_end_execution(self):
        puzzle, board = self.make_puzzle()
        device = MockAndroid(puzzle, board)
        self.assertTrue(execute(device, puzzle, board, puzzle.plan(board), lambda *_: True, interval=0))
        self.assertEqual(len(device.taps), 3)
        self.assertFalse(any(device.board))

    def test_batch_verifies_after_multiple_taps(self):
        puzzle, board = self.make_puzzle()
        device = MockAndroid(puzzle, board)
        self.assertTrue(execute(device, puzzle, board, puzzle.plan(board), lambda *_: True,
                                interval=0, batch_size=8))
        self.assertEqual((len(device.taps), device.captures), (3, 2))

    def test_stale_plan_and_no_op_fail_closed(self):
        puzzle, board = self.make_puzzle()
        stale = MockAndroid(puzzle, (0,) * 9)
        with self.assertRaisesRegex(ToolkitError, "before tap"):
            execute(stale, puzzle, board, puzzle.plan(board), lambda *_: True, interval=0)
        self.assertEqual(stale.taps, [])
        no_op = MockAndroid(puzzle, board, apply=False)
        with self.assertRaisesRegex(ToolkitError, "Could not verify taps 1"):
            execute(no_op, puzzle, board, puzzle.plan(board), lambda *_: True, timeout=0, interval=0)
        self.assertEqual(len(no_op.taps), 1)

    def test_step_limit_and_cancel(self):
        puzzle, board = self.make_puzzle()
        device = MockAndroid(puzzle, board)
        self.assertFalse(execute(device, puzzle, board, puzzle.plan(board), lambda *_: False, interval=0))
        self.assertEqual(device.taps, [])
        self.assertFalse(execute(device, puzzle, board, puzzle.plan(board), lambda *_: True, interval=0, limit=1))
        self.assertEqual(len(device.taps), 1)


if __name__ == "__main__":
    unittest.main()
