#!/usr/bin/env python3
"""Faithfully render demo.cast (asciinema v2) to PNG frames, then ffmpeg -> mp4.

No content edits: every frame is the terminal grid fed with the recorded
bytes at recorded timestamps.
"""
import json
import os
import subprocess

import pyte
from PIL import Image, ImageDraw, ImageFont

CAST = "demo.cast"
FRAMES = "/tmp/opencode/demo_frames"
OUT = "demo.mp4"
FPS = 10
FONT_PATH = "/usr/share/fonts/TTF/DejaVuSansMono.ttf"
FONT_SIZE = 18

os.makedirs(FRAMES, exist_ok=True)
header = json.loads(open(CAST).readline())
cols, rows = header["width"], header["height"]
events = [json.loads(l) for l in open(CAST) if l.startswith("[")]
duration = events[-1][0] + 2.0

font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
# Measure cell size.
probe = Image.new("RGB", (10, 10))
d0 = ImageDraw.Draw(probe)
bbox = d0.textbbox((0, 0), "M" * 100, font=font)
cell_w = (bbox[2] - bbox[0]) / 100
bbox2 = d0.textbbox((0, 0), "Mg", font=font)
cell_h = bbox2[3] - bbox2[1] + 6
W, H = int(cols * cell_w) + 20, int(rows * cell_h) + 20


def draw(screen):
    img = Image.new("RGB", (W, H), "black")
    d = ImageDraw.Draw(img)
    for y in range(rows):
        for x in range(cols):
            ch = screen.buffer[y][x]
            if ch.data == " ":
                continue
            fg = ch.fg if ch.fg not in ("default",) else "white"
            bg = ch.bg if ch.bg not in ("default",) else "black"
            if ch.reverse:
                fg, bg = bg, fg
            if ch.bold:
                fg = "bright_" + fg if not fg.startswith("bright_") else fg
            px, py = 10 + x * cell_w, 10 + y * cell_h
            colormap = {"black": (0, 0, 0), "white": (255, 255, 255),
                        "bright_white": (255, 255, 255)}
            d.rectangle([px, py, px + cell_w, py + cell_h],
                        fill=colormap.get(bg, (0, 0, 0)))
            d.text((px, py), ch.data, font=font,
                   fill=colormap.get(fg, (255, 255, 255)))
    # Cursor
    cx, cy = screen.cursor.x, screen.cursor.y
    d.rectangle([10 + cx * cell_w, 10 + cy * cell_h,
                 10 + (cx + 1) * cell_w, 10 + (cy + 1) * cell_h],
                outline=(255, 255, 255))
    return img


screen = pyte.Screen(cols, rows)
stream = pyte.ByteStream(screen)
n_frames = int(duration * FPS)
ev_idx = 0
t = 0.0
frame_no = 0
for frame_no in range(n_frames):
    t = frame_no / FPS
    while ev_idx < len(events) and events[ev_idx][0] <= t:
        _, typ, data = events[ev_idx]
        if typ == "o":
            stream.feed(data.encode("utf-8", "replace"))
        ev_idx += 1
    # Save every frame (simple, keeps A/V timeline exact).
    draw(screen).save(f"{FRAMES}/f{frame_no:05d}.png")

print(f"wrote {frame_no + 1} frames, {W}x{H}")
subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS),
                "-i", f"{FRAMES}/f%05d.png",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-vf", "scale=1280:-2", OUT], check=True)
print("wrote", OUT)
