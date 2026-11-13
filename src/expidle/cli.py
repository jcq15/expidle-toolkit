"""Console entry point."""
import argparse
from collections import Counter
from pathlib import Path
import sys

from PIL import Image

from .adb import Android
from .core import ToolkitError, execute
from .games.arrow import RULES
from .games.arrow_farm import FarmProfile, current_board, farm
from .games.arrow_screen import ArrowPuzzle, Profile


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="expidle")
    cli.add_argument("--serial", help="ADB device serial, required when multiple are connected")
    cli.add_argument("--adb", default="adb", help="ADB executable")
    commands = cli.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="capture the foreground game to PNG")
    capture.add_argument("output", type=Path)
    arrow = commands.add_parser("arrow", help="recognize and solve the Arrow Puzzle")
    actions = arrow.add_subparsers(dest="action", required=True)
    calibration = actions.add_parser("calibrate", help="create a local profile from one screenshot")
    calibration.add_argument("--difficulty", choices=RULES, required=True)
    calibration.add_argument("--profile", type=Path, required=True)
    calibration.add_argument("--image", type=Path, help="use a saved screenshot instead of ADB")
    run = actions.add_parser("solve", help="preview a solution or execute verified taps")
    run.add_argument("--profile", type=Path, required=True)
    run.add_argument("--image", type=Path, help="offline PNG, preview only")
    run.add_argument("--overlay", type=Path, help="save annotated board PNG")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="preview without tapping (default)")
    mode.add_argument("--step", action="store_true", help="confirm every tap")
    mode.add_argument("--apply", action="store_true", help="confirm once, send all taps, then verify")
    run.add_argument("--limit", type=int, help="maximum number of taps this run")
    run.add_argument("--batch-size", type=int, help="taps per check with --apply (1-12, default: whole board)")
    buttons = actions.add_parser("calibrate-farm", help="learn the two button labels from screenshots")
    buttons.add_argument("--profile", type=Path, required=True)
    buttons.add_argument("--farm-profile", type=Path, required=True)
    buttons.add_argument("--active-image", type=Path, required=True)
    buttons.add_argument("--solved-image", type=Path, required=True)
    for option in ("--active-box", "--reward-box"):
        buttons.add_argument(option, nargs=4, type=int, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
                             required=True, help="tight text rectangle in screenshot coordinates")
    repeat = actions.add_parser("farm", help="play a fixed number of expert rounds")
    repeat.add_argument("--profile", type=Path, required=True)
    repeat.add_argument("--farm-profile", type=Path, required=True)
    repeat.add_argument("--rounds", type=int, required=True)
    repeat.add_argument("--batch-size", type=int, help="taps per check (1-12, default: whole board)")
    repeat.add_argument("--apply", action="store_true", help="confirm once, then play")
    for action in (run, repeat):
        action.add_argument("--tap-delay-ms", type=int, default=0,
                            help="extra pause between taps (0-1000 ms, default: 0)")
    return cli


def save_png(frame: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        frame.save(output, format="PNG")


def show_plan(puzzle: ArrowPuzzle, state, moves) -> None:
    columns = {}
    for (col, _), value in zip(puzzle.rules.cells, state):
        columns.setdefault(col, []).append(str(value + 1))
    for index, values in enumerate(columns.values(), 1):
        print(f"Column {index}: {' '.join(values)}")
    print(f"Minimum taps: {len(moves)}")
    for move, count in Counter(moves).items():
        print(f"  Cell {move.cell + 1:2} at {move.point}: {count} tap(s)")


def main(argv=None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    try:
        if args.command == "capture":
            save_png(Android(args.adb, args.serial).capture(), args.output)
            return 0
        if args.action == "calibrate-farm":
            puzzle = ArrowPuzzle(Profile.load(args.profile))
            with Image.open(args.active_image) as active, Image.open(args.solved_image) as solved:
                buttons = FarmProfile.create(puzzle, active, solved, tuple(args.active_box), tuple(args.reward_box))
            buttons.save(args.farm_profile)
            print(f"Saved {args.farm_profile}")
            return 0
        if args.action in ("solve", "farm"):
            if not 0 <= args.tap_delay_ms <= 1000:
                cli.error("--tap-delay-ms must be 0-1000")
            if args.batch_size is not None and not 1 <= args.batch_size <= 12:
                cli.error("--batch-size must be 1-12")
        if args.action == "farm":
            if args.rounds < 1:
                cli.error("--rounds must be positive")
            puzzle = ArrowPuzzle(Profile.load(args.profile))
            if puzzle.profile.difficulty != "expert":
                raise ToolkitError("Farm mode requires an expert board profile.")
            buttons = FarmProfile.load(args.farm_profile)
            device = Android(args.adb, args.serial, tap_delay_ms=args.tap_delay_ms)
            board = current_board(device.capture(), puzzle, buttons)
            mode = f"{args.batch_size} taps per batch" if args.batch_size else "whole board"
            print(f"Expert farm: {args.rounds} round(s), {mode}.")
            if puzzle.solved(board):
                print("The reward screen is open. Starting will tap it to open the first new board.")
            else:
                print(f"The first board takes {len(puzzle.plan(board))} taps.")
            if not args.apply:
                print("Dry run. No taps sent.")
                return 0
            if input("Type FARM to start: ") != "FARM":
                print("Cancelled.")
                return 0
            farm(device, puzzle, buttons, args.rounds, args.batch_size,
                 report=lambda message: print(message, flush=True))
            return 0
        live = args.image is None
        wants_input = args.action == "solve" and (args.step or args.apply)
        if wants_input and not live:
            cli.error("--step and --apply need a live ADB device")
        if args.action == "solve" and args.limit is not None and args.limit < 1:
            cli.error("--limit must be at least 1")
        device = Android(args.adb, args.serial, tap_delay_ms=getattr(args, "tap_delay_ms", 0)) if live else None
        if device is not None:
            frame = device.capture()
        else:
            with Image.open(args.image) as image:
                frame = image.convert("RGB")
        if args.action == "calibrate":
            from .calibration import wizard
            wizard(frame, args.difficulty, args.profile)
            print(f"Saved {args.profile}")
            return 0

        puzzle = ArrowPuzzle(Profile.load(args.profile))
        state = puzzle.read(frame)
        moves = puzzle.plan(state)
        show_plan(puzzle, state, moves)
        if args.overlay:
            save_png(puzzle.overlay(frame, state, moves), args.overlay)
        if not wants_input:
            print("Dry run. No taps sent.")
            return 0
        if not moves:
            print("Board is already solved.")
            return 0
        if args.apply and input("Type APPLY to execute the displayed plan: ") != "APPLY":
            print("Cancelled.")
            return 0

        tap_count = min(len(moves), args.limit or len(moves))
        batch_size = (args.batch_size or tap_count) if args.apply else 1

        def approve(move, index):
            if args.step:
                if input(f"Tap {index}, cell {move.cell + 1} at {move.point}? [y/N] ").lower() != "y":
                    return False
            if args.step:
                print(f"Sending tap {index} at {move.point}", flush=True)
            else:
                end = min(index + batch_size - 1, tap_count)
                print(f"Sending taps {index}-{end}", flush=True)
            return True

        solved = execute(
            device, puzzle, state, moves, approve, limit=args.limit,
            batch_size=batch_size,
        )
        print("Verified: all cells are 1." if solved else "Stopped with an unfinished board.")
        return 0
    except (ToolkitError, OSError, ValueError, EOFError) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
