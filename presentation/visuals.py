"""Логотип команды и иллюстрация-радар для презентации."""
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent / "img"
PINK, VIOLET, LAV, WHITE = "#FF0053", "#520978", "#8A83D1", "#FFFFFF"
plt.rcParams["font.family"] = "Segoe UI"


def radar(ax, color_rings, color_dots, labels=None, label_color="#310F53"):
    ax.set_aspect("equal"); ax.axis("off")
    for r, a in ((1.0, 0.9), (0.72, 0.7), (0.44, 0.55)):
        ax.add_patch(plt.Circle((0, 0), r, fill=False, lw=2, ec=color_rings, alpha=a))
    for ang in range(0, 360, 45):
        ax.plot([0, math.cos(math.radians(ang))], [0, math.sin(math.radians(ang))], color=color_rings, lw=1, alpha=0.35)
    # сектор «луча»
    ax.add_patch(matplotlib.patches.Wedge((0, 0), 1.0, 20, 65, color=PINK, alpha=0.18))
    pts = [(0.85, 28), (0.55, 85), (0.72, 145), (0.42, 205), (0.88, 250), (0.62, 318), (0.3, 20), (0.25, 280)]
    for i, (r, ang) in enumerate(pts):
        x, y = r * math.cos(math.radians(ang)), r * math.sin(math.radians(ang))
        ax.add_patch(plt.Circle((x, y), 0.055 if i < 2 else 0.035, color=color_dots if i < 2 else LAV))
        if labels and i < len(labels):
            ax.text(x + 0.07, y + 0.04, labels[i], fontsize=11, color=label_color, fontweight="bold")
    ax.set_xlim(-1.08, 1.6 if labels else 1.08); ax.set_ylim(-1.08, 1.08)


# Логотип: радар + название (белый, для тёмного титульного слайда)
fig = plt.figure(figsize=(8, 1.7), dpi=220)
ax = fig.add_axes([0.0, 0.02, 0.21, 0.96])
radar(ax, WHITE, PINK)
fig.text(0.24, 0.56, "АГЕНТЫ МОСКВЫ", fontsize=30, fontweight="bold", color=WHITE, va="center")
fig.text(0.24, 0.2, "радар слабых технологических сигналов", fontsize=15, color="#E8DDF5", va="center")
fig.savefig(OUT / "logo.png", transparent=True)

# Иллюстрация для слайда «О команде и решении» — радар с примерами найденных сигналов
fig = plt.figure(figsize=(9, 4.15), dpi=200)
ax = fig.add_axes([0.02, 0.03, 0.96, 0.94])
radar(ax, VIOLET, PINK, labels=["Know Your Agent", "HTTP 402-платежи", "zk-KYC", "Tokenized deposits", "Agentic commerce", "Purpose-bound money"])
fig.savefig(OUT / "hero.png", transparent=True)
print("ok")
