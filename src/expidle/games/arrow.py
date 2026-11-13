"""Arrow Puzzle board geometry and exact minimum-tap solver."""
from dataclasses import dataclass
from itertools import product
from math import hypot

from ..core import Point, ToolkitError

Board = tuple[int, ...]


@dataclass(frozen=True)
class Rules:
    modulus: int
    cells: tuple[tuple[int, int], ...]
    hexagonal: bool

    def neighbors(self, index: int) -> tuple[int, ...]:
        q, r = self.cells[index]
        near = []
        for other, (oq, other_r) in enumerate(self.cells):
            dx, dy = oq - q, other_r - r
            distance = max(abs(dx), abs(dy), abs(dx + dy)) if self.hexagonal else max(abs(dx), abs(dy))
            if distance <= 1:
                near.append(other)
        return tuple(near)

    def turn(self, board: Board, cell: int) -> Board:
        changed = list(board)
        for index in self.neighbors(cell):
            changed[index] = (changed[index] + 1) % self.modulus
        return tuple(changed)

    def centers(self, bounds: tuple[int, int, int, int]) -> tuple[tuple[Point, ...], int]:
        # Axial hex coordinates project to columns and staggered rows.
        x0, y0, x1, y1 = bounds
        if x1 <= x0 or y1 <= y0:
            raise ToolkitError("Board bounds must have positive width and height.")
        grid = [(q, r + q / 2 if self.hexagonal else r) for q, r in self.cells]
        xs, ys = zip(*grid)
        dx = (x1 - x0) / (max(xs) - min(xs))
        dy = (y1 - y0) / (max(ys) - min(ys))
        spacing = min(dy, hypot(dx, dy / 2)) if self.hexagonal else min(dx, dy)
        points = tuple((round(x0 + (x - min(xs)) * dx), round(y0 + (y - min(ys)) * dy)) for x, y in grid)
        return points, max(5, round(spacing * 0.33))


def square(size: int) -> Rules:
    return Rules(4, tuple(product(range(size), repeat=2)), False)


def hexagon(modulus: int) -> Rules:
    cells = tuple((q, r) for q, r in product(range(-3, 4), repeat=2) if abs(q + r) <= 3)
    return Rules(modulus, cells, True)


RULES = {"easy": square(3), "medium": square(4), "hard": hexagon(2), "expert": hexagon(6)}


def field_solutions(matrix: list[list[int]], target: list[int], prime: int):
    """Enumerate all solutions using elimination over a prime field."""
    width = len(matrix[0])
    rows = [[value % prime for value in row + [rhs]] for row, rhs in zip(matrix, target)]
    pivots: list[int] = []
    for col in range(width):
        rank = len(pivots)
        pivot = next((i for i in range(rank, len(rows)) if rows[i][col]), None)
        if pivot is None:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        inverse = pow(rows[rank][col], -1, prime)
        rows[rank] = [(value * inverse) % prime for value in rows[rank]]
        for i, row in enumerate(rows):
            if i != rank and row[col]:
                factor = row[col]
                rows[i] = [(a - factor * b) % prime for a, b in zip(row, rows[rank])]
        pivots.append(col)
    if any(row[-1] for row in rows[len(pivots):]):
        return
    free = [col for col in range(width) if col not in pivots]
    for values in product(range(prime), repeat=len(free)):
        result = [0] * width
        for col, value in zip(free, values):
            result[col] = value
        for col, row in zip(pivots, rows):
            result[col] = (row[-1] - sum(row[j] * result[j] for j in free)) % prime
        yield tuple(result)


def candidates(matrix: list[list[int]], target: list[int], modulus: int):
    if modulus == 2:
        yield from field_solutions(matrix, target, 2)
    elif modulus == 4:
        # Lift x = low + 2 * high. First solve for low, then solve the residual.
        for low in field_solutions(matrix, target, 2):
            residual = [(rhs - sum(a * b for a, b in zip(row, low))) // 2 for row, rhs in zip(matrix, target)]
            for high in field_solutions(matrix, residual, 2):
                yield tuple(a + 2 * b for a, b in zip(low, high))
    elif modulus == 6:
        # Chinese remainder theorem combines solutions mod 2 and mod 3.
        binary = tuple(field_solutions(matrix, target, 2))
        for ternary in field_solutions(matrix, target, 3):
            for parity in binary:
                yield tuple((3 * a + 4 * b) % 6 for a, b in zip(parity, ternary))


def solve(rules: Rules, board: Board) -> tuple[int, ...]:
    size = len(rules.cells)
    if len(board) != size or any(not 0 <= value < rules.modulus for value in board):
        raise ToolkitError("Invalid Arrow Puzzle board.")
    neighborhoods = [set(rules.neighbors(row)) for row in range(size)]
    matrix = [[int(col in near) for col in range(size)] for near in neighborhoods]
    target = [-value for value in board]
    answer = min(candidates(matrix, target, rules.modulus), key=sum, default=None)
    if answer is None:
        raise ToolkitError("Recognized board has no solution. Check the screenshot and calibration.")
    if any((sum(a * b for a, b in zip(row, answer)) - rhs) % rules.modulus for row, rhs in zip(matrix, target)):
        raise ToolkitError("Computed tap plan did not pass simulation.")
    return answer
