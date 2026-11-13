"""Interactive calibration from a screenshot, without touching the device."""
from pathlib import Path

from PIL import Image

from .core import ToolkitError
from .games.arrow import RULES
from .games.arrow_screen import ArrowPuzzle, calibrate


def wizard(frame: Image.Image, difficulty: str, output: Path) -> None:
    try:
        import tkinter as tk
        from PIL import ImageTk
        from tkinter import messagebox
    except ImportError as error:
        raise ToolkitError("Tk is required for the calibration window.") from error

    root = tk.Tk()
    root.title("Arrow Puzzle calibration")
    rules = RULES[difficulty]
    scale = min(1, root.winfo_screenwidth() * 0.82 / frame.width, root.winfo_screenheight() * 0.79 / frame.height)
    size = round(frame.width * scale), round(frame.height * scale)
    picture = ImageTk.PhotoImage(frame.resize(size, Image.Resampling.LANCZOS))
    guide = tk.StringVar()
    tk.Label(root, textvariable=guide, wraplength=550).pack(pady=6)
    canvas = tk.Canvas(root, width=size[0], height=size[1], highlightthickness=0)
    canvas.pack()
    canvas.create_image(0, 0, image=picture, anchor="nw")
    anchors = []
    points = ()
    bounds = ()
    labels = {}
    selected = None
    saved = False
    prompts = (
        "Click the center of a cell on the leftmost edge.",
        "Click the center of a cell on the rightmost edge.",
        "Click the center of a cell on the top edge.",
        "Click the center of a cell on the bottom edge.",
    )

    def redraw():
        canvas.delete("markers")
        if not points:
            guide.set(prompts[len(anchors)])
        else:
            missing = sorted(set(range(1, rules.modulus + 1)) - set(labels.values()))
            guide.set(f"Click a cell, then press its digit (1–{rules.modulus}). Missing: {missing or 'none'}.")
        for cell, (x, y) in enumerate(points):
            x, y = x * scale, y * scale
            color = "#ffb347" if cell == selected else "#68ffff"
            canvas.create_oval(x - 9, y - 9, x + 9, y + 9, outline=color, width=2, tags="markers")
            if cell in labels:
                canvas.create_text(x + 11, y - 10, text=str(labels[cell]), fill=color, tags="markers")

    def click(event):
        nonlocal bounds, points, selected
        x, y = round(event.x / scale), round(event.y / scale)
        if points:
            selected = min(range(len(points)), key=lambda i: (points[i][0] - x)**2 + (points[i][1] - y)**2)
        else:
            anchors.append((x, y))
            if len(anchors) == 4:
                bounds = anchors[0][0], anchors[2][1], anchors[1][0], anchors[3][1]
                try:
                    points, _ = rules.centers(bounds)
                except ToolkitError as error:
                    anchors.clear()
                    messagebox.showerror("Calibration", str(error))
        redraw()

    def key(event):
        if selected is not None and event.char in "123456" and event.char:
            value = int(event.char)
            if value <= rules.modulus:
                labels[selected] = value
                redraw()

    def reset():
        nonlocal points, bounds, selected
        points, bounds, selected = (), (), None
        anchors.clear()
        labels.clear()
        redraw()

    def save():
        nonlocal saved
        try:
            if not points:
                raise ToolkitError("Mark all four edges first.")
            profile = calibrate(frame, difficulty, bounds, labels)
            puzzle = ArrowPuzzle(profile)
            board = puzzle.read(frame)
            if not messagebox.askokcancel("Confirm calibration", "Read values in columns, top to bottom:\n" +
                                           " ".join(str(value + 1) for value in board)):
                return
            profile.save(output)
            saved = True
            root.destroy()
        except (ToolkitError, OSError) as error:
            messagebox.showerror("Calibration", str(error))

    toolbar = tk.Frame(root)
    toolbar.pack()
    tk.Button(toolbar, text="Reset", command=reset).pack(side="left", padx=5, pady=5)
    tk.Button(toolbar, text="Save profile", command=save).pack(side="left", padx=5, pady=5)
    canvas.bind("<Button-1>", click)
    root.bind("<Key>", key)
    redraw()
    root.mainloop()
    if not saved:
        raise ToolkitError("Calibration was cancelled.")
