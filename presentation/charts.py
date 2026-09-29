"""Графики для презентации — строятся из реальных файлов метрик репозитория."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "backend" / "data" / "model"
OUT = Path(__file__).resolve().parent / "img"
OUT.mkdir(exist_ok=True)

PINK, VIOLET, LAV, DARK, GREY = "#FF0053", "#520978", "#8A83D1", "#310F53", "#9A95B5"
for f in []:
    font_manager.fontManager.addfont(str(f))
plt.rcParams.update({"font.family": "Segoe UI", "font.size": 13, "axes.edgecolor": "#DDDAE8", "axes.labelcolor": DARK, "xtick.color": DARK, "ytick.color": DARK})

metrics = json.loads((MODEL / "metrics.json").read_text(encoding="utf-8"))
comp = json.loads((MODEL / "decision_model_comparison.json").read_text(encoding="utf-8"))
model = json.loads((MODEL / "signal_model.json").read_text(encoding="utf-8"))
live = json.loads((MODEL / "live_eval.json").read_text(encoding="utf-8"))["runs"]


def clean(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


# 1. Jev vs правила
fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=200)
labels = ["F1", "Precision", "ROC-AUC", "F1 только по\nответам модели"]
h = comp["heuristic_rules"]
j = comp["jev"]
hv = [h["cv5"]["f1"], h["cv5"]["precision"], h["cv5"]["roc_auc"], h["decision_model_only"]["f1"]]
jv = [j["cv5"]["f1"], j["cv5"]["precision"], j["cv5"]["roc_auc"], j["decision_model_only"]["f1"]]
x = range(len(labels))
b1 = ax.bar([i - 0.2 for i in x], hv, 0.38, color=LAV, label="Словарные правила")
b2 = ax.bar([i + 0.2 for i in x], jv, 0.38, color=PINK, label="Jev (TypeSafe)")
for bars in (b1, b2):
    for r in bars:
        ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 0.01, f"{r.get_height():.2f}", ha="center", fontsize=11, color=DARK, fontweight="bold")
ax.set_xticks(list(x), labels)
ax.set_ylim(0.6, 1.05)
ax.legend(frameon=False, loc="upper left", ncol=2)
clean(ax)
fig.tight_layout()
fig.savefig(OUT / "jev_vs_rules.png", transparent=True)

# 2. Перенос на новую область
lodo = metrics["leave_one_domain_out"]
fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
names = list(lodo)
vals = [lodo[n]["f1"] for n in names]
ax.barh(names, vals, color=[PINK if v >= 0.95 else VIOLET for v in vals])
for i, v in enumerate(vals):
    ax.text(v + 0.005, i, f"{v:.2f}", va="center", fontsize=12, color=DARK, fontweight="bold")
ax.set_xlim(0.8, 1.04)
ax.set_xlabel("F1 на области, которой не было в обучении")
clean(ax)
fig.tight_layout()
fig.savefig(OUT / "lodo.png", transparent=True)

# 3. Веса признаков
RU = {
    "log_total_works": "Объём публикаций", "recent_share": "Доля публикаций за 3 года", "growth": "Рост публикаций",
    "age_years": "Возраст темы", "wiki_exists": "Статья в Википедии", "log_wiki_views": "Популярность в Википедии",
    "log_gh_repos_12m": "Новые репозитории GitHub", "log_hn_12m": "Обсуждения инженеров", "fresh_preprints": "Свежие препринты",
    "share_science": "Доля научных источников", "log_evidence": "Число подтверждений", "specific_tech": "Конкретная технология · Jev",
    "mass_adoption": "Массовое внедрение · Jev", "market_leaders": "Рынок с лидерами · Jev", "standard": "Отраслевой стандарт · Jev",
    "early_stage": "Ранняя стадия · Jev", "independent": "Независимые участники · Jev", "hype": "Маркетинговый шум · Jev",
    "novelty": "Новизна · Jev", "benefit": "Конкретное преимущество · Jev", "textbook": "Учебниковая идея · Jev", "maturity": "Уровень зрелости · Jev",
}
w = sorted(zip(model["features"], model["coef"]), key=lambda t: -abs(t[1]))[:12][::-1]
fig, ax = plt.subplots(figsize=(7.0, 5.0), dpi=200)
ax.barh([RU.get(f, f) for f, _ in w], [c for _, c in w], color=[PINK if c > 0 else VIOLET for _, c in w])
ax.axvline(0, color=GREY, lw=1)
ax.set_xlabel("вес:  ← признак зрелости   |   признак слабого сигнала →", fontsize=11)
ax.tick_params(axis="y", labelsize=11)
clean(ax)
fig.tight_layout()
fig.savefig(OUT / "weights.png", transparent=True)

# 4. Живые запросы
doms = []
for r in live:
    if r["domain"] and r["domain"] not in doms:
        doms.append(r["domain"])
with_wl = {r["domain"]: r for r in live if r["mode"].startswith("с базой")}
fig, ax = plt.subplots(figsize=(7.4, 4.3), dpi=200)
x = range(len(doms))
conf = [with_wl[d]["confident_75"] for d in doms]
hits = [with_wl[d]["dataset_hits_in_top15"] for d in doms]
ax.bar([i - 0.2 for i in x], conf, 0.38, color=LAV, label="Сигналов с уверенностью ≥ 75% (из 15)")
ax.bar([i + 0.2 for i in x], hits, 0.38, color=PINK, label="Совпало с сигналами организатора")
for i, (c, hh) in enumerate(zip(conf, hits)):
    ax.text(i - 0.2, c + 0.2, str(c), ha="center", fontsize=11, fontweight="bold", color=DARK)
    ax.text(i + 0.2, hh + 0.2, str(hh), ha="center", fontsize=11, fontweight="bold", color=DARK)
ax.set_xticks(list(x), [d.replace(" ", "\n") for d in doms], fontsize=11)
ax.set_ylim(0, 18)
ax.legend(frameon=False, loc="upper right", fontsize=10)
clean(ax)
fig.tight_layout()
fig.savefig(OUT / "live.png", transparent=True)

# 5. Конвейер
steps = [
    ("Запрос", "на русском,\nв свободной\nформе"),
    ("План", "12 подтем\nRU / EN"),
    ("Сбор", "arXiv · OpenAlex\nGDELT · Хабр\nGitHub · HN · Wiki"),
    ("Кандидаты", "LLM по текстам\n+ майнинг\nтерминов"),
    ("Jev", "15 вопросов\nк каждому\nкандидату"),
    ("Модель", "22 признака →\nвероятность\nи вклады"),
    ("Фильтры", "зрелое\nстандарт · хайп\nпродукт"),
    ("Досье", "ТОП-15\nисключённые\nисточники"),
]
fig, ax = plt.subplots(figsize=(13, 3.2), dpi=200)
ax.set_xlim(0, len(steps) * 1.6)
ax.set_ylim(0, 2.2)
ax.axis("off")
for i, (t, s) in enumerate(steps):
    x0 = i * 1.6 + 0.05
    col = PINK if t == "Jev" else (VIOLET if t in ("Модель", "Фильтры") else "#F3EFFA")
    tc = "white" if col != "#F3EFFA" else DARK
    ax.add_patch(FancyBboxPatch((x0, 0.35), 1.38, 1.5, boxstyle="round,pad=0.02,rounding_size=0.15", fc=col, ec="none"))
    ax.text(x0 + 0.69, 1.45, t, ha="center", va="center", fontsize=13, fontweight="bold", color=tc)
    ax.text(x0 + 0.69, 0.85, s, ha="center", va="center", fontsize=9, color=tc, linespacing=1.3)
    if i < len(steps) - 1:
        ax.annotate("", xy=(x0 + 1.58, 1.1), xytext=(x0 + 1.42, 1.1), arrowprops=dict(arrowstyle="-|>", color=GREY, lw=1.5))
fig.tight_layout()
fig.savefig(OUT / "pipeline.png", transparent=True)
print("ok", sorted(p.name for p in OUT.iterdir()))
