"""Сборка презентации из шаблона ЛЦТ: обязательные слайды 7–11 заполняются без изменения дизайна,
остальные слайды — в стиле шаблона (фон и цвета из макета, розовая плашка заголовка, белые карточки)."""
import copy
import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Pt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TEMPLATE = ROOT.parent / "ЛЦТ2026 Шаблон презентации.pptx"
OUT = HERE / "Агенты_Москвы_Радар_слабых_сигналов.pptx"
IMG = HERE / "img"
MODEL = ROOT / "backend" / "data" / "model"

PINK, VIOLET, DARK, WHITE, LIGHT = RGBColor(0xFF, 0x00, 0x53), RGBColor(0x52, 0x09, 0x78), RGBColor(0x31, 0x0F, 0x53), RGBColor(0xFF, 0xFF, 0xFF), RGBColor(0xF3, 0xEF, 0xFA)
FONT = "Montserrat"
metrics = json.loads((MODEL / "metrics.json").read_text(encoding="utf-8"))
comp = json.loads((MODEL / "decision_model_comparison.json").read_text(encoding="utf-8"))

prs = Presentation(str(TEMPLATE))
S = {i + 1: s for i, s in enumerate(prs.slides)}


def shape(slide, sid):
    return next(sh for sh in slide.shapes if sh.shape_id == sid)


def set_runs(para, texts):
    """Заменяет текст в существующих runs абзаца, сохраняя их форматирование."""
    runs = para.runs
    for r, t in zip(runs, texts):
        r.text = t
    for r in runs[len(texts):]:
        r.text = ""


def set_para_text(sh, idx, text):
    set_runs(sh.text_frame.paragraphs[idx], [text])


def add_para_like(sh, src_idx, text):
    """Добавляет абзац с форматированием абзаца-образца."""
    src = sh.text_frame.paragraphs[src_idx]._p
    new = copy.deepcopy(src)
    sh.text_frame._txBody.append(new)
    p = sh.text_frame.paragraphs[-1]
    set_runs(p, [text])
    return p


# ---------- Слайд 7: титульный ----------
s7 = S[7]
s7.placeholders[0].text = "Радар слабых сигналов"
s7.placeholders[12].text = "Команда «АГЕНТЫ МОСКВЫ» · Задача №1 Газпромбанк.Тех · ЛЦТ 2026"
_lg = s7.placeholders[11].insert_picture(str(IMG / "logo.png"))
_lg.crop_left = _lg.crop_right = _lg.crop_top = _lg.crop_bottom = 0
_lg.left, _lg.top, _lg.width, _lg.height = Emu(420000), Emu(430000), Emu(4700000), Emu(1000000)

# ---------- Слайд 8: о команде и суть ----------
s8 = S[8]
_hero = s8.placeholders[10].insert_picture(str(IMG / "hero.png"))
_hero.crop_left = _hero.crop_right = _hero.crop_top = _hero.crop_bottom = 0
_hero.left, _hero.top, _hero.width, _hero.height = Emu(250000), Emu(420000), Emu(5900000), Emu(2720000)
set_para_text(shape(s8, 5), 0, "По открытому запросу сервис за 5–15 минут собирает свежие статьи, препринты, новости и сигналы разработчиков, "
              "выделяет конкретные технологии, отсекает зрелое, стандарты и хайп и выдаёт ТОП-15 ранних сигналов с уверенностью, объяснением и проверяемыми источниками.")
set_para_text(shape(s8, 8), 0, "Decision-модель Jev (согласована с экспертами Газпромбанк.Тех) за один проход отвечает вероятностями на 15 вопросов о текстах источников. "
              "Ответы — признаки нашего интерпретируемого классификатора: каждое решение раскладывается на вклады признаков.")
t = shape(s8, 14)
ps = t.text_frame.paragraphs
set_runs(ps[0], ["Капитан: ", "Сороковых Иван Евгеньевич, продакт-менеджер, ИИ-агенты"])
set_runs(ps[1], ["Кол-во участников: ", "2 человека"])
set_runs(ps[2], ["Краткое описание: ", ""])
set_runs(ps[3], ["продакт по ИИ-агентам и RAG + инженер-аналитик с опытом в ML "])
set_runs(ps[4], ["Иван — ИИ-агенты и цифровые продукты; Михаил — инженер НОВАТЭК (Тюмень)"])
set_runs(ps[5], ["Город и регион: Москва, Тюмень"])

# ---------- Слайд 9: участники (лишние карточки удалены) ----------
s9 = S[9]
cards = {
    1: {"name": 15, "text": 9},
    2: {"name": 58, "text": 57},
}
people = [
    ("Иван Сороковых", ["Капитан, продакт-менеджер", "Telegram: @mcshpak", "ИИ-агенты, RAG, мультиагентные системы", "Цифровые продукты, криптовалюты"]),
    ("Михаил Дементьев", ["Backend, ML", "Telegram: @dementevma", "Инженер НОВАТЭК, офис в Тюмени", "Изучает газовые месторождения"]),
]
for k, (nm, lines) in zip((1, 2), people):
    set_para_text(shape(s9, cards[k]["name"]), 0, nm)
    tb = shape(s9, cards[k]["text"])
    for i, ln in enumerate(lines):
        set_para_text(tb, i, ln)
for sid in (59, 60, 61, 62, 63, 64, 65, 66, 67, 4, 5, 6):
    el = shape(s9, sid)._element
    el.getparent().remove(el)
s9.placeholders[0].text = "АГЕНТЫ МОСКВЫ"
# Фото участников на месте пустых рамок шаблона (рамки удаляем, размер и позиция — по сетке карточек)
for sid in (2, 3):
    el = shape(s9, sid)._element
    el.getparent().remove(el)
PH = 1480000
for card_left, photo in ((346076, "ivan.png"), (2651394, "mikhail.png")):
    s9.shapes.add_picture(str(IMG / photo), Emu(card_left + (2192713 - PH) // 2), Emu(1760000), Emu(PH), Emu(PH))

# ---------- Слайд 10: история ----------
s10 = S[10]
s10.placeholders[0].text = "История команды"
set_para_text(shape(s10, 37), 0, "Иван строит продукты на ИИ-агентах и RAG, Михаил — инженер НОВАТЭК, работает с данными газовых месторождений. "
              "Объединились на ЛЦТ: продукт + инженерный анализ данных.")
set_para_text(shape(s10, 43), 0, "Ручной поиск ранних технологий занимает дни и тонет в мейнстриме — "
              "хотели сделать его быстрым и объяснимым с decision-моделями.")
tb = shape(s10, 40)
set_runs(tb.text_frame.paragraphs[0], ["Нет отрицательных примеров — собрали свои 140 и честную оценку с переносом на новую область.", "", ""])
set_runs(tb.text_frame.paragraphs[1], ["Лимиты и блокировки источников, битый JSON от LLM — отказоустойчивый сбор, резервные квоты, устойчивый разбор.", "", ""])

# ---------- Слайд 11: техническая и маркетинговая суть ----------
s11 = S[11]
tech = shape(s11, 3)
set_para_text(tech, 0, "7 открытых источников: arXiv, OpenAlex, GDELT, Хабр, GitHub, Hacker News, Википедия.")
for line in [
    "Кандидаты: LLM извлекает технологии из найденных текстов + статистический майнинг терминов.",
    "Jev отвечает на 15 вопросов о доказательствах: зрелость, стандарт, хайп, новизна, продукт или технология.",
    "Логистическая регрессия на 22 признаках: вероятность и вклад каждого признака.",
    "Явные фильтры исключения с причиной; досье на русском только по источникам.",
    "Python · FastAPI · PostgreSQL · React · Docker. F1 = 0,946 на датасете.",
]:
    add_para_like(tech, 0, line)
mk = shape(s11, 7)
set_runs(mk.text_frame.paragraphs[0], ["Ранний технологический радар для платформы ИИ-аналитики банка: дни ручной работы аналитика → 10 минут.", ""])
for line in [
    "Каждый сигнал с источниками, уверенностью и причинами — готово к обсуждению на техкомитете.",
    "Дёшево в эксплуатации: Jev — $0,042 за 1 млн токенов; есть локальная замена Kev для закрытого контура.",
    "Развитие: подписки на темы, еженедельный мониторинг, алерты, дообучение на оценках аналитиков.",
]:
    add_para_like(mk, 0, line)

# ---------- Удаляем все остальные слайды шаблона ----------
keep = {7, 8, 9, 10, 11}
sldIdLst = prs.slides._sldIdLst
for i, sldId in reversed(list(enumerate(list(sldIdLst), 1))):
    if i not in keep:
        prs.part.drop_rel(sldId.rId)
        sldIdLst.remove(sldId)

# Переименовываем оставшиеся слайды по порядку, чтобы имена частей не пересеклись с новыми.
from pptx.opc.packuri import PackURI
for i, sl in enumerate(prs.slides, 1):
    sl.part.partname = PackURI(f"/ppt/slides/slide{i}.xml")

LAYOUT = prs.slide_layouts[4]  # «Заголовок и объект»: фоновый градиент шаблона


def new_slide(title):
    s = prs.slides.add_slide(LAYOUT)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    pill = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(346075), Emu(324562), Emu(int(550000 + 215000 * len(title))), Emu(620919))
    pill.adjustments[0] = 0.2
    pill.fill.solid(); pill.fill.fore_color.rgb = PINK
    pill.line.fill.background()
    tf = pill.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = Emu(180000)
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = title.upper()
    r.font.name = FONT; r.font.size = Pt(20); r.font.bold = True; r.font.color.rgb = WHITE
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    return s


def card(s, l, t, w, h, fill=WHITE):
    c = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(l), Emu(t), Emu(w), Emu(h))
    c.adjustments[0] = 0.06
    c.fill.solid(); c.fill.fore_color.rgb = fill
    c.line.fill.background()
    c.shadow.inherit = False
    return c


def text(s, l, t, w, h, items, size=14, color=DARK, bold_first=False):
    tb = s.shapes.add_textbox(Emu(l), Emu(t), Emu(w), Emu(h))
    tf = tb.text_frame; tf.word_wrap = True
    for i, it in enumerate(items):
        if isinstance(it, str):
            it = {"t": it}
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(it.get("after", 6))
        r = p.add_run(); r.text = it["t"]
        r.font.name = FONT; r.font.size = Pt(it.get("size", size)); r.font.bold = it.get("bold", bold_first and i == 0)
        r.font.color.rgb = it.get("color", color)
    return tb


def pic(s, name, l, t, w=None, h=None):
    return s.shapes.add_picture(str(IMG / name), Emu(l), Emu(t), Emu(w) if w else None, Emu(h) if h else None)


CARD_T, CARD_H = 1211284, 4989492
FULL_L, FULL_W = 346075, 11500000

# 12. Проблема и решение
s = new_slide("Проблема и решение")
cols = [
    ("Проблема", ["Слабые сигналы ищут вручную: дни работы аналитика.", "Выдачу забивают зрелые технологии, стандарты и маркетинговые анонсы.", "Выводы субъективны и не воспроизводимы."]),
    ("Что делаем", ["Открытый запрос → поиск по 7 источникам RU/EN.", "Jev читает доказательства и отвечает на 15 вопросов о зрелости и шуме.", "Классификатор даёт вероятность и объяснение, фильтры — причину отсева."]),
    ("Результат", ["ТОП-15 ранних технологий с досье на русском.", "Список исключённых с причинами.", "Каждый источник: дата, тип, язык, уровень доверия, пометка LLM-резюме."]),
]
w = 3650000
for i, (h, lines) in enumerate(cols):
    l = 346075 + i * (w + 275000)
    card(s, l, CARD_T, w, 3450000, WHITE if i != 1 else LIGHT)
    text(s, l + 250000, CARD_T + 250000, w - 500000, 3000000, [{"t": h, "size": 22, "bold": True, "color": PINK if i == 1 else VIOLET, "after": 14}] + [{"t": "• " + x, "after": 12} for x in lines], size=15)
kpis = [("15", "ранних технологий на запрос"), ("5–17 мин", "время обработки запроса"), ("7", "открытых источников RU / EN")]
for i, (big, small) in enumerate(kpis):
    l = 346075 + i * (w + 275000)
    card(s, l, CARD_T + 3600000, w, CARD_H - 3600000, PINK if i == 1 else WHITE)
    text(s, l + 250000, CARD_T + 3700000, w - 500000, CARD_H - 3700000, [{"t": big, "size": 30, "bold": True, "color": WHITE if i == 1 else PINK, "after": 0}, {"t": small, "size": 13, "color": WHITE if i == 1 else DARK}])

# 13. Как работает
s = new_slide("Как это работает")
card(s, FULL_L, CARD_T, FULL_W, CARD_H)
pic(s, "pipeline.png", FULL_L + 150000, CARD_T + 250000, w=FULL_W - 300000)
text(s, FULL_L + 350000, CARD_T + 3250000, FULL_W - 700000, 1600000, [
    {"t": "Сбор, анализ и интерфейс разделены (collectors / pipeline / api + frontend), всё в Docker Compose с PostgreSQL.", "after": 8},
    {"t": "Каждое обращение к моделям журналируется: какая модель, зачем, что ответила — вкладка «Журнал моделей» на странице запроса.", "after": 8},
    {"t": "Выдача никогда не формируется из памяти LLM: кандидат проходит сбор доказательств, досье пишется только по найденным документам.", "after": 8},
], size=14)

# 14. Jev
s = new_slide("Почему Jev — наше преимущество")
card(s, FULL_L, CARD_T, 4700000, CARD_H, LIGHT)
text(s, FULL_L + 250000, CARD_T + 250000, 4200000, CARD_H - 500000, [
    {"t": "Decision-модель вместо «спросить LLM»", "size": 18, "bold": True, "color": VIOLET, "after": 12},
    "Jev (TypeSafe AI) не генерирует текст — возвращает калиброванные вероятности на типизированные вопросы.",
    "15 вопросов к каждому кандидату за один проход: массовое внедрение? стандарт? хайп? ранняя стадия? это продукт или класс технологий?",
    "$0,042 за 1 млн входных токенов — проверка всех кандидатов запроса стоит центы.",
    {"t": "Использование согласовано с экспертами Газпромбанк.Тех 23.09.2026. Локальная замена — открытая Kev (Apache-2.0) с тем же API.", "color": PINK, "bold": True},
], size=14)
card(s, FULL_L + 4900000, CARD_T, 6600000, CARD_H)
pic(s, "jev_vs_rules.png", FULL_L + 5050000, CARD_T + 150000, w=6300000)
text(s, FULL_L + 5150000, CARD_T + 4250000, 6200000, 600000, ["Одинаковые доказательства и классификатор, 5-кратная кросс-валидация на 240 примерах."], size=11)

# 15. Интерпретируемость
s = new_slide("Интерпретируемость модели")
card(s, FULL_L, CARD_T, 6900000, CARD_H)
pic(s, "weights.png", FULL_L + 150000, CARD_T + 150000, w=6600000)
card(s, FULL_L + 7100000, CARD_T, 4400000, CARD_H, LIGHT)
text(s, FULL_L + 7350000, CARD_T + 250000, 3900000, CARD_H - 500000, [
    {"t": "22 признака с понятным смыслом", "size": 18, "bold": True, "color": VIOLET, "after": 12},
    "11 наблюдаемых: рост и возраст темы в OpenAlex, свежие препринты arXiv, новые репозитории GitHub, известность в Википедии.",
    "11 ответов Jev о текстах источников.",
    "Логистическая регрессия: вклад = вес × стандартизованное значение. В карточке сигнала — диаграмма «за / против».",
    {"t": "Веса хранятся в открытом JSON — модель полностью проверяема.", "bold": True, "color": PINK},
], size=14)

# 16. Качество
cv = metrics["cv5"]
c75 = metrics["confident_75"]
s = new_slide("Качество на датасете")
tiles = [("F1", cv["f1"]), ("Precision", cv["precision"]), ("Recall", cv["recall"]), ("ROC-AUC", cv["roc_auc"])]
for i, (k, v) in enumerate(tiles):
    l = FULL_L + i * 1400000
    card(s, l, CARD_T, 1300000, 1350000, WHITE)
    text(s, l + 60000, CARD_T + 150000, 1180000, 1200000, [{"t": f"{v:.3f}".replace(".", ","), "size": 26, "bold": True, "color": PINK, "after": 2}, {"t": k, "size": 13, "color": DARK}])
card(s, FULL_L, CARD_T + 1500000, 5500000, CARD_H - 1500000, LIGHT)
text(s, FULL_L + 250000, CARD_T + 1700000, 5100000, CARD_H - 1900000, [
    {"t": "Как считали — честно", "size": 18, "bold": True, "color": VIOLET, "after": 10},
    "100 сигналов организатора + 140 наших отрицательных: зрелые технологии, стандарты, хайп, общие области.",
    "Доказательства собраны тем же кодом, что и в живом поиске, на фиксированную дату.",
    f"Уверенность ≥ 75%: у {c75['share_of_positives_above_075']:.0%} сигналов, точность в этой зоне {c75['precision_above_075']:.0%}.",
    "Порог ТЗ 75–80% превышен.",
    "Отчёт: backend/data/model/metrics.json и страница «Методология» на стенде.",
], size=14)
card(s, FULL_L + 5700000, CARD_T, 5800000, CARD_H)
text(s, FULL_L + 5950000, CARD_T + 150000, 5400000, 500000, [{"t": "Перенос на новую область", "size": 16, "bold": True, "color": VIOLET}])
pic(s, "lodo.png", FULL_L + 5800000, CARD_T + 650000, w=5600000)

# 17. Отсев
s = new_slide("Отсев зрелого, стандартов и шума")
card(s, FULL_L, CARD_T, FULL_W, CARD_H)
rules = [
    ("Нерелевантно", "релевантность запросу < 0,34", "«Multi-agent trajectory planning» для запроса про финтех"),
    ("Не инновация", "документ, репозиторий, явление, организация", "«Fintech engineering handbook», «stablecoin contagion»"),
    ("Продукт / компания", "Jev: это название одного продукта ≥ 0,6", "«zLend» — приложение, а не класс технологий"),
    ("Отраслевой стандарт", "Jev: действующий стандарт ≥ 0,6", "ISO 20022, OAuth 2.0"),
    ("Зрелая технология", "массовое внедрение, рынок с лидерами, > 20 000 работ, популярная статья Википедии", "«Quantum key distribution»: 5 800 просмотров/мес, давно в литературе"),
    ("Маркетинговый шум", "Jev: шум ≥ 0,75 и научных источников < 20%", "анонсы без технического содержания"),
    ("Мало подтверждений", "< 3 подтверждений или только блоги и пресс-релизы", "одиночный пресс-релиз стартапа"),
]
tbl = s.shapes.add_table(len(rules) + 1, 3, Emu(FULL_L + 200000), Emu(CARD_T + 200000), Emu(FULL_W - 400000), Emu(CARD_H - 400000)).table
tbl.columns[0].width = Emu(2400000); tbl.columns[1].width = Emu(4300000); tbl.columns[2].width = Emu(FULL_W - 400000 - 6700000)
for j, hdr in enumerate(["Причина", "Правило", "Пример из живой выдачи"]):
    rows = [hdr] + [r[j] for r in rules]
    for i, val in enumerate(rows):
        cell = tbl.cell(i, j)
        cell.text = val
        cell.fill.solid(); cell.fill.fore_color.rgb = VIOLET if i == 0 else (LIGHT if i % 2 else WHITE)
        for p in cell.text_frame.paragraphs:
            for r in p.runs:
                r.font.name = FONT; r.font.size = Pt(12 if i else 13); r.font.bold = i == 0 or j == 0
                r.font.color.rgb = WHITE if i == 0 else (PINK if j == 0 else DARK)

# 18. Живые запросы
s = new_slide("Живые запросы")
card(s, FULL_L, CARD_T, 7200000, CARD_H)
pic(s, "live.png", FULL_L + 150000, CARD_T + 200000, w=6900000)
card(s, FULL_L + 7400000, CARD_T, 4100000, CARD_H, LIGHT)
text(s, FULL_L + 7650000, CARD_T + 250000, 3650000, CARD_H - 500000, [
    {"t": "5–17 минут на запрос", "size": 20, "bold": True, "color": PINK, "after": 10},
    "Требование — до 20 минут. Подготовка модели (сбор признаков для 240 примеров, ~30 мин) выполняется один раз заранее.",
    "В каждой теме — 15 сигналов, у всех уверенность ≥ 75%.",
    "Для тем датасета выдача сверяется с сигналами организатора; остальное — новые кандидаты, найденные в открытых источниках.",
    {"t": "Прогоны 24.09 на стенде разработки; стенд жюри работает на финальной модели.", "size": 11},
], size=13)

# 19. Источники и доверие
s = new_slide("Источники и доверие")
cols = [
    ("Высокое доверие", ["Научные публикации (OpenAlex, DOI)", "Регуляторы и международные организации", "Ведущие деловые и научные издания"]),
    ("Среднее", ["Препринты arXiv", "Отраслевые СМИ, Хабр", "Репозитории кода GitHub"]),
    ("Пониженное", ["Пресс-релизы и блоги компаний", "Соцсети, обсуждения сообществ", "Не могут быть единственным основанием"]),
]
w = 3650000
for i, (h, lines) in enumerate(cols):
    l = 346075 + i * (w + 275000)
    card(s, l, CARD_T, w, 2500000, WHITE)
    text(s, l + 250000, CARD_T + 250000, w - 500000, 2200000, [{"t": h, "size": 19, "bold": True, "color": [VIOLET, VIOLET, PINK][i], "after": 12}] + [{"t": "• " + x, "after": 8} for x in lines], size=14)
card(s, FULL_L, CARD_T + 2700000, FULL_W, CARD_H - 2700000, LIGHT)
text(s, FULL_L + 300000, CARD_T + 2900000, FULL_W - 600000, CARD_H - 3000000, [
    {"t": "Проверяемость каждого вывода", "size": 18, "bold": True, "color": VIOLET, "after": 10},
    "У каждого источника: название, ссылка, дата публикации, тип, язык оригинала, уровень доверия и критерий. "
    "Иностранные материалы — с русским резюме и пометкой «автоматическое резюме (LLM)».",
    "Отказоустойчивость: кэш, повторы, общий ограничитель частоты для всех запросов, предохранитель для недоступных источников, нейтральная подстановка признаков с пометкой в досье.",
    "Журнал моделей: для каждого обращения к Jev и GigaChat видно, что спросили и что ответили.",
], size=14)

# 20. Бизнес-эффект и развитие
s = new_slide("Эффект для банка и развитие")
cols = [
    ("Сейчас", ["Веб-стенд: запрос → ТОП-15 за 5–15 минут", "Досье с источниками и объяснением уверенности", "Журнал моделей для аудита", "Docker: разворачивается одной командой"]),
    ("Далее", ["Подписки на темы и еженедельный мониторинг", "Алерты о росте сигнала", "Технологический радар банка: наблюдать / изучать / пилотировать", "Дообучение на оценках аналитиков"]),
    ("Внедрение", ["Интеграция в платформу ИИ-аналитики Газпромбанка", "Kev локально — закрытый контур без облачных API", "Экспорт отчётов для техкомитетов", "Стоимость запроса — центы"]),
]
for i, (h, lines) in enumerate(cols):
    l = 346075 + i * (w + 275000)
    card(s, l, CARD_T, w, 3700000, WHITE if i != 1 else LIGHT)
    text(s, l + 250000, CARD_T + 250000, w - 500000, 3300000, [{"t": h, "size": 22, "bold": True, "color": PINK if i == 1 else VIOLET, "after": 14}] + [{"t": "• " + x, "after": 12} for x in lines], size=15)
card(s, FULL_L, CARD_T + 3850000, FULL_W, 850000, PINK)
text(s, FULL_L + 300000, CARD_T + 3930000, FULL_W - 600000, 800000, [{"t": "От дней ручного поиска — к 10 минутам: ранние сигналы с доказательствами для техкомитета банка", "size": 18, "bold": True, "color": WHITE}])
text(s, FULL_L, CARD_T + CARD_H + 60000, FULL_W, 400000, [{"t": "Стенд: http://89.169.170.106/   ·   Код: github.com/Krackenhell/lct-2026-weak-signals", "size": 14, "bold": True, "color": WHITE}])

prs.save(str(OUT))
print("saved", OUT, "slides:", len(prs.slides))
