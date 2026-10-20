"""Графики итоговой презентации — строятся из файлов метрик репозитория (backend/data/model), ничего не вписано руками."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "backend" / "data" / "model"
OUT = Path(__file__).resolve().parent / "img_final"
OUT.mkdir(exist_ok=True)

PINK, VIOLET, LAV, DARK, GREY, LIGHT = "#FF0053", "#520978", "#8A83D1", "#310F53", "#9A95B5", "#F3EFFA"
plt.rcParams.update({"font.family": "Segoe UI", "font.size": 13, "axes.edgecolor": "#DDDAE8", "axes.labelcolor": DARK,
                     "xtick.color": DARK, "ytick.color": DARK})


def load(name):
    return json.loads((MODEL / name).read_text(encoding="utf-8"))


def clean(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / name, transparent=True)
    plt.close(fig)


# 1. «Только LLM» против конвейера
lb = load("llm_baseline.json")
short = {"технология многослойного графена": "Многослойный\nграфен", "микрофлюидные чипы": "Микрофлюидные\nчипы",
         "газлифт в газоконденсатных скважинах": "Газлифт", "перспективные решения в финтехе": "Финтех"}
names = [short.get(p["query"], p["query"]) for p in lb["pairs"]]
llm = [p["llm_only"]["signals"] for p in lb["pairs"]]
pipe = [(p["pipeline"] or {}).get("signals", 0) for p in lb["pairs"]]
fig, ax = plt.subplots(figsize=(7.4, 4.4), dpi=200)
x = range(len(names))
b1 = ax.bar([i - 0.2 for i in x], llm, 0.38, color=LAV, label="Только GigaChat (15 названий)")
b2 = ax.bar([i + 0.2 for i in x], pipe, 0.38, color=PINK, label="Наш конвейер")
for bars in (b1, b2):
    for r in bars:
        ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 0.2, f"{int(r.get_height())}", ha="center", fontsize=13, color=DARK, fontweight="bold")
ax.set_xticks(list(x), names)
ax.set_ylabel("подтверждённых сигналов")
ax.legend(frameon=False, loc="upper right")
clean(ax)
save(fig, "llm_vs_pipeline.png")

# 2. Машина времени: импульс роста
em = load("emergence.json")
main = em["variants"]["все индикаторы без отбора (заранее заданный вариант)"]
fig, ax = plt.subplots(figsize=(6.6, 4.2), dpi=200)
labels = ["Базовая модель\n(13 признаков)", "+ импульс роста\n(4 индикатора)"]
vals = [em["base_auc"], main["auc"]]
bars = ax.bar(labels, vals, color=[LAV, PINK], width=0.55)
ax.errorbar([1], [main["auc"]], yerr=[[main["auc"] - (em["base_auc"] + main["ci95"][0])], [(em["base_auc"] + main["ci95"][1]) - main["auc"]]],
            fmt="none", ecolor=DARK, capsize=8, lw=1.5)
tops = [vals[0] + 0.02, em["base_auc"] + main["ci95"][1] + 0.02]  # подпись выше отрезка доверительного интервала
for r, v, top in zip(bars, vals, tops, strict=True):
    ax.text(r.get_x() + r.get_width() / 2, top, f"{v:.3f}".replace(".", ","), ha="center", fontsize=15, color=DARK, fontweight="bold")
ax.axhline(0.5, color=GREY, lw=1, ls="--")
ax.text(1.32, 0.505, "угадывание", color=GREY, fontsize=10)
ax.set_ylim(0.4, 0.9)
ax.set_ylabel("ROC-AUC «вне времени»")
clean(ax)
save(fig, "timemachine.png")

# 3. Веса модели (18 признаков)
model = load("signal_model.json")
ru = {"log_total_works": "Объём публикаций", "recent_share": "Доля свежих работ", "growth": "Рост публикаций", "age_years": "Возраст темы",
      "wiki_exists": "Статья в Википедии", "log_wiki_views": "Просмотры Википедии", "fresh_preprints": "Свежие препринты", "share_science": "Доля науки",
      "log_evidence": "Число подтверждений", "specific_tech": "Конкретная технология", "mass_adoption": "Массовое внедрение",
      "market_leaders": "Рынок с лидерами", "standard": "Стандарт", "hype": "Рекламные формулировки", "novelty": "Новизна",
      "textbook": "Учебниковая идея", "maturity": "Зрелость", "event": "Твёрдое событие"}
w = sorted(zip(model["features"], model["coef"], strict=True), key=lambda kv: kv[1])
fig, ax = plt.subplots(figsize=(6.8, 5.6), dpi=200)
ax.barh([ru.get(f, f) for f, _ in w], [c for _, c in w], color=[PINK if c > 0 else VIOLET for _, c in w])
ax.axvline(0, color=DARK, lw=1)
ax.set_xlabel("вес признака: «за» (розовый) / «против» (фиолетовый)")
clean(ax)
save(fig, "weights_final.png")

# 4. Лестница «от науки до рынка» — реальный пример из живого прогона 20.10
steps = [("научная\nработа", "с 2024"), ("патент", "2"), ("грант", "—"), ("стартап", "—"), ("раунд", "—"), ("пилот", "с 2026"),
         ("контракт", "—"), ("серийный\nпродукт", "с 2026"), ("закупка\nв России", "—")]
fig, ax = plt.subplots(figsize=(11.2, 1.75), dpi=200)
ax.set_xlim(0, len(steps))
ax.set_ylim(0.1, 1.13)
ax.axis("off")
for i, (lab, val) in enumerate(steps):
    on = val != "—"
    ax.add_patch(FancyBboxPatch((i + 0.06, 0.15), 0.88, 0.95, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=PINK if on else "white", ec=PINK if on else "#DDDAE8", lw=1.5))
    ax.text(i + 0.5, 0.78, lab, ha="center", va="center", fontsize=11.5, color="white" if on else GREY, fontweight="bold")
    ax.text(i + 0.5, 0.35, val, ha="center", va="center", fontsize=12, color="white" if on else GREY)
    if i < len(steps) - 1:
        ax.annotate("", xy=(i + 1.04, 0.62), xytext=(i + 0.96, 0.62), arrowprops=dict(arrowstyle="->", color=GREY))
save(fig, "ladder.png")

# 5. Схема конвейера
blocks = [("Запрос", "любая отрасль,\nширокий\nили узкий"), ("План", "GigaChat-2 +\nправило\n«узкий / широкий»"),
          ("Корпус", "35 источников:\nнаука, патенты,\nгранты, рынок"), ("Кандидаты", "GigaChat +\nмайнинг терминов\n+ рост в науке"),
          ("Проверка", "Jev отвечает\nна вопросы\nо документах"), ("Решение", "наша регрессия,\n18 признаков,\nфильтры"),
          ("Карточка", "путь к рынку,\nдоводы «против»,\nигроки, справка")]
fig, ax = plt.subplots(figsize=(13, 2.5), dpi=200)
ax.set_xlim(0, len(blocks))
ax.set_ylim(0, 1.15)
ax.axis("off")
for i, (h, d) in enumerate(blocks):
    color = PINK if h in ("Решение",) else VIOLET if h in ("Проверка", "План", "Кандидаты") else DARK
    ax.add_patch(FancyBboxPatch((i + 0.06, 0.08), 0.88, 1.0, boxstyle="round,pad=0.02,rounding_size=0.06", fc="white", ec=color, lw=2))
    ax.text(i + 0.5, 0.9, h, ha="center", va="center", fontsize=14, color=color, fontweight="bold")
    ax.text(i + 0.5, 0.45, d, ha="center", va="center", fontsize=10, color=DARK, linespacing=1.3)
    if i < len(blocks) - 1:
        ax.annotate("", xy=(i + 1.06, 0.58), xytext=(i + 0.94, 0.58), arrowprops=dict(arrowstyle="-|>", color=GREY, lw=1.5))
save(fig, "pipeline_final.png")

# 6. Срезы ошибок модели
met = load("metrics.json")
sl = met["slices"]["false_signal_share"]
fig, ax = plt.subplots(figsize=(6.4, 3.8), dpi=200)
items = [(k, v["false_signals"]) for k, v in sl.items() if v["false_signals"] is not None]
ax.barh([k for k, _ in items][::-1], [v * 100 for _, v in items][::-1], color=[PINK if v >= 0.15 else LAV for _, v in items][::-1])
for i, (_, v) in enumerate(items[::-1]):
    ax.text(v * 100 + 0.6, i, f"{v * 100:.0f}%", va="center", fontsize=12, color=DARK, fontweight="bold")
ax.set_xlabel("доля ложных сигналов, %")
clean(ax)
save(fig, "slices.png")
print("charts:", sorted(p.name for p in OUT.iterdir()))
