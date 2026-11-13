"""Read calibrated glyphs from unscaled Android screenshots."""
from dataclasses import dataclass
import json
from pathlib import Path
from statistics import median

from PIL import Image, ImageDraw

from ..core import Move, Point, RecognitionError, ToolkitError
from .arrow import Board, RULES, solve

GLYPH = 24


def signature(frame: Image.Image, center: Point, radius: int) -> int:
    x, y = center
    crop = frame.crop((x - radius, y - radius, x + radius + 1, y + radius + 1)).convert("L")
    side = crop.width
    px = crop.load()
    background = median(
        [px[i, edge] for i in range(side) for edge in (0, side - 1)]
        + [px[edge, i] for i in range(side) for edge in (0, side - 1)]
    )
    contrast = [abs(value - background) for value in crop.get_flattened_data()]
    peak = max(contrast)
    if peak < 18:
        raise RecognitionError("Cell has no visible glyph.")
    mask = Image.new("L", crop.size)
    mask.putdata([255 if value >= max(12, peak * 0.43) else 0 for value in contrast])
    bounds = mask.getbbox()
    if bounds is None:
        raise RecognitionError("Cell has no visible glyph.")
    left, top, right, bottom = bounds
    width, height = right - left, bottom - top
    if min(width, height) < 3 or left == 0 or top == 0 or right == side or bottom == side:
        raise RecognitionError("Glyph is cut off or does not fit the calibration.")
    scale = (GLYPH - 2) / max(width, height)
    glyph = mask.crop(bounds).resize(
        (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS
    )
    centered = Image.new("L", (GLYPH, GLYPH))
    centered.paste(glyph, ((GLYPH - glyph.width) // 2, (GLYPH - glyph.height) // 2))
    return int.from_bytes(centered.point(lambda value: 255 if value >= 128 else 0, mode="1").tobytes(), "big")


@dataclass(frozen=True)
class Profile:
    difficulty: str
    size: tuple[int, int]
    bounds: tuple[int, int, int, int]
    templates: tuple[tuple[int, ...], ...]

    @classmethod
    def load(cls, path: Path) -> "Profile":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["format"] != 1:
                raise ValueError("unsupported format")
            profile = cls(
                data["difficulty"], tuple(data["size"]), tuple(data["bounds"]),
                tuple(tuple(int(mask, 16) for mask in group) for group in data["templates"]),
            )
            if len(profile.templates) != RULES[profile.difficulty].modulus or not all(profile.templates):
                raise ValueError("one or more glyph classes are missing")
            profile.geometry()
            return profile
        except (ValueError, KeyError, TypeError, OSError) as error:
            raise ToolkitError(f"Invalid profile {path}: {error}") from error

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "format": 1, "difficulty": self.difficulty, "size": self.size,
            "bounds": self.bounds, "templates": [[format(mask, "x") for mask in group] for group in self.templates],
        }
        with path.open("x", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
            file.write("\n")

    def geometry(self) -> tuple[tuple[Point, ...], int]:
        points, radius = RULES[self.difficulty].centers(self.bounds)
        width, height = self.size
        if any(not (radius <= x < width - radius and radius <= y < height - radius) for x, y in points):
            raise ToolkitError("Calibration extends beyond the screen.")
        return points, radius


def calibrate(
    frame: Image.Image, difficulty: str, bounds: tuple[int, int, int, int], labels: dict[int, int],
) -> Profile:
    rules = RULES[difficulty]
    profile = Profile(difficulty, frame.size, bounds, ())
    points, radius = profile.geometry()
    templates: list[list[int]] = [[] for _ in range(rules.modulus)]
    for cell, value in labels.items():
        if not (0 <= cell < len(points) and 1 <= value <= rules.modulus):
            raise ToolkitError("Invalid cell index or glyph label.")
        templates[value - 1].append(signature(frame, points[cell], radius))
    if not all(templates):
        raise ToolkitError(f"Label at least one example of each value 1–{rules.modulus}.")
    return Profile(difficulty, frame.size, bounds, tuple(tuple(dict.fromkeys(group)) for group in templates))


class ArrowPuzzle:
    def __init__(self, profile: Profile):
        self.profile = profile
        self.rules = RULES[profile.difficulty]
        self.points, self.radius = profile.geometry()

    def read(self, frame: Image.Image) -> Board:
        if frame.size != self.profile.size:
            raise RecognitionError("Screen size or rotation changed. Use the matching profile.")
        values = []
        for index, point in enumerate(self.points):
            try:
                glyph = signature(frame, point, self.radius)
            except RecognitionError as error:
                raise RecognitionError(f"Cell {index + 1}: {error}") from error
            count = glyph.bit_count()
            distances = sorted(
                (min((glyph ^ sample).bit_count() / (count + sample.bit_count()) for sample in group), value)
                for value, group in enumerate(self.profile.templates)
            )
            (best, value), (runner_up, _) = distances[:2]
            if best > 0.29 or runner_up - best < 0.055:
                raise RecognitionError(f"Cell {index + 1} is ambiguous (distance {best:.2f}).")
            values.append(value)
        return tuple(values)

    def plan(self, state: Board) -> list[Move]:
        return [Move(cell, point) for cell, (point, count) in enumerate(zip(self.points, solve(self.rules, state)))
                for _ in range(count)]

    def predict(self, state: Board, move: Move) -> Board:
        return self.rules.turn(state, move.cell)

    def solved(self, state: Board) -> bool:
        return not any(state)

    def overlay(self, frame: Image.Image, state: Board, moves: list[Move]) -> Image.Image:
        from collections import Counter
        counts = Counter(move.cell for move in moves)
        canvas = frame.copy().convert("RGB")
        draw = ImageDraw.Draw(canvas)
        for cell, (x, y) in enumerate(self.points):
            r = self.radius
            draw.ellipse((x - r, y - r, x + r, y + r), outline="#66f6ff", width=2)
            draw.text((x, y - r), str(state[cell] + 1), fill="#66f6ff", anchor="mb", font_size=max(12, r // 2))
            if counts[cell]:
                draw.text((x, y + r), f"x{counts[cell]}", fill="#ffe175", anchor="mt", font_size=max(12, r // 2))
        return canvas
