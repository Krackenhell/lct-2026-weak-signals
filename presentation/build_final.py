"""Итоговая презентация к финалу (20.10.2026): копия основной презентации команды с обновлёнными цифрами и новыми слайдами.

Основная презентация (Агенты_Москвы_Радар_слабых_сигналов.pptx) не меняется. Титул, «О команде», «Команда», «История»
и «Коротко о решении» берутся из неё (дизайн шаблона ЛЦТ), тексты с устаревшими числами заменяются. Содержательные слайды
собираются заново в том же стиле (розовая плашка заголовка, белые и сиреневые карточки). Числа — из файлов метрик и прогонов.

Запуск: python presentation/charts_final.py && python presentation/build_final.py
"""
import copy
import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.opc.packuri import PackURI
from pptx.util import Emu, Pt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASE = HERE / "Агенты_Москвы_Радар_слабых_сигналов.pptx"
OUT = HERE / "Агенты_Москвы_Радар_ИТОГ.pptx"
IMG = HERE / "img_final"
MODEL = ROOT / "backend" / "data" / "model"

PINK, VIOLET, DARK, WHITE, LIGHT = RGBColor(0xFF, 0x00, 0x53), RGBColor(0x52, 0x09, 0x78), RGBColor(0x31, 0x0F, 0x53), RGBColor(0xFF, 0xFF, 0xFF), RGBColor(0xF3, 0xEF, 0xFA)
FONT = "Montserrat"
metrics = json.loads((MODEL / "metrics.json").read_text(encoding="utf-8"))
gates = json.loads((MODEL / "gates_h4.json").read_text(encoding="utf-8"))
emerg = json.loads((MODEL / "emergence.json").read_text(encoding="utf-8"))
lb = json.loads((MODEL / "llm_baseline.json").read_text(encoding="utf-8"))

prs = Presentation(str(BASE))
SL = list(prs.slides)


def num(v, d=3):
    return f"{v:.{d}f}".replace(".", ",")


def rewrite(sh, lines):
    """Оставляет форматирование первого абзаца фигуры, заменяет весь текст строками lines."""
    tf = sh.text_frame
    first = tf.paragraphs[0]._p
    for p in list(tf.paragraphs)[1:]:
        tf._txBody.remove(p._p)
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else None
        if p is None:
            tf._txBody.append(copy.deepcopy(first))
            p = tf.paragraphs[-1]
        runs = p.runs
        if runs:
            runs[0].text = line
            for r in runs[1:]:
                r.text = ""
        else:
            p.add_run().text = line


def find(slide, start):
    return next(sh for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip().startswith(start))


# ---------- 1. Титул: подзаголовок в одну строку ----------
SL[0].placeholders[12].text = "«АГЕНТЫ МОСКВЫ» · Газпромбанк.Тех · ЛЦТ 2026"

# ---------- 2. О команде: уникальность и краткое описание ----------
s2 = SL[1]
rewrite(find(s2, "По открытому запросу"), [
    "По запросу из любой отрасли сервис за 2–4 минуты находит до 15 технологий, которые только начинают расти, и показывает для каждой "
    "путь от науки до рынка, доказательства, доводы «против» и кто над ней работает."])
rewrite(find(s2, "Decision-модель Jev"), [
    "GigaChat-2 строит план и пишет справку, decision-модель Jev проверяет каждый документ и каждое утверждение, а решение «сигнал или нет» "
    "принимает наша прозрачная модель на 18 признаках. Простой вопрос к LLM дал 4 сигнала, конвейер — 22 на тех же темах."])

# ---------- 5. Коротко о решении ----------
s5 = SL[4]
rewrite(find(s5, "7 открытых источников"), [
    "≈30 открытых источников: научные базы, новости RU/EN/ZH, гранты, стартапы, патенты и веб-поиск (Brave API).",
    "Узкий запрос из любой отрасли: правило «широкий / узкий» и растущие поднаправления по научной литературе.",
    "Jev отвечает на вопросы о каждом документе; GigaChat-2 — план и справка; решение — наша регрессия на 18 признаках.",
    "Лестница «от науки до рынка», доводы «против», карта игроков, проверка каждого утверждения справки.",
    "Python · FastAPI · React · Docker; один сервер без GPU. 443 автотеста.",
])
rewrite(find(s5, "Ранний технологический радар"), [
    "Ранний технологический радар для банка и его клиентов: дни ручного поиска → 2–4 минуты.",
    "«Под вашу компанию»: загрузили стратегию — видно, какие сигналы с ней связаны.",
    "Подписка на тему и прогноз с проверкой: сигнал отслеживается, прогноз проверяется через полгода.",
    "Отечественные модели; для закрытого контура — локальная модель без облачных API.",
])

# ---------- удаляем старые содержательные слайды (6–14) ----------
sldIdLst = prs.slides._sldIdLst
for i, sldId in reversed(list(enumerate(list(sldIdLst), 1))):
    if i > 5:
        prs.part.drop_rel(sldId.rId)
        sldIdLst.remove(sldId)
for i, sl in enumerate(prs.slides, 1):
    sl.part.partname = PackURI(f"/ppt/slides/slide{i}.xml")

LAYOUT = next(lay for lay in prs.slide_layouts if lay.name == "Заголовок и объект")
CARD_T, CARD_H = 1211284, 4989492
FULL_L, FULL_W = 346075, 11500000


def new_slide(title):
    s = prs.slides.add_slide(LAYOUT)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    pill = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(346075), Emu(324562), Emu(int(550000 + 205000 * len(title))), Emu(620919))
    pill.adjustments[0] = 0.2
    pill.fill.solid()
    pill.fill.fore_color.rgb = PINK
    pill.line.fill.background()
    tf = pill.text_frame
    tf.word_wrap = False
    tf.margin_left = tf.margin_right = Emu(180000)
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = title.upper()
    r.font.name, r.font.size, r.font.bold, r.font.color.rgb = FONT, Pt(20), True, WHITE
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    return s


def card(s, l, t, w, h, fill=WHITE):
    c = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(l), Emu(t), Emu(w), Emu(h))
    c.adjustments[0] = 0.06
    c.fill.solid()
    c.fill.fore_color.rgb = fill
    c.line.fill.background()
    c.shadow.inherit = False
    return c


def text(s, l, t, w, h, items, size=14, color=DARK):
    tb = s.shapes.add_textbox(Emu(l), Emu(t), Emu(w), Emu(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, it in enumerate(items):
        it = {"t": it} if isinstance(it, str) else it
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(it.get("after", 6))
        r = p.add_run()
        r.text = it["t"]
        r.font.name, r.font.size, r.font.bold = FONT, Pt(it.get("size", size)), it.get("bold", False)
        r.font.color.rgb = it.get("color", color)
    return tb


def pic(s, name, l, t, w=None, h=None):
    return s.shapes.add_picture(str(IMG / name), Emu(l), Emu(t), Emu(w) if w else None, Emu(h) if h else None)


def table(s, rows, l, t, w, h, widths, size=12, first_col_pink=True):
    tbl = s.shapes.add_table(len(rows), len(rows[0]), Emu(l), Emu(t), Emu(w), Emu(h)).table
    for j, cw in enumerate(widths):
        tbl.columns[j].width = Emu(cw)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.text = str(val)
            cell.fill.solid()
            cell.fill.fore_color.rgb = VIOLET if i == 0 else (LIGHT if i % 2 else WHITE)
            for p in cell.text_frame.paragraphs:
                for r in p.runs:
                    r.font.name, r.font.size = FONT, Pt(size if i else size + 1)
                    r.font.bold = i == 0 or (j == 0 and first_col_pink)
                    r.font.color.rgb = WHITE if i == 0 else (PINK if j == 0 and first_col_pink else DARK)
    return tbl


def three_cols(s, cols, top=CARD_T, height=3450000, size=15, mid_light=True):
    w = 3650000
    for i, (h, lines) in enumerate(cols):
        l = 346075 + i * (w + 275000)
        card(s, l, top, w, height, LIGHT if (i == 1 and mid_light) else WHITE)
        text(s, l + 250000, top + 220000, w - 500000, height - 300000,
             [{"t": h, "size": 21, "bold": True, "color": PINK if i == 1 else VIOLET, "after": 12}] + [{"t": "• " + x, "after": 10} for x in lines], size=size)


# ---------- 6. Проблема и решение ----------
s = new_slide("Проблема и решение")
three_cols(s, [
    ("Проблема", ["Ранние технологии ищут вручную — дни работы аналитика.", "Выдачу забивают зрелые темы, стандарты и реклама.",
                  "Языковая модель «из памяти» называет общие и уже известные темы."]),
    ("Что делаем", ["Запрос из любой отрасли — широкий или узкий.", "Поиск по ≈30 открытым источникам и проверка каждого документа моделью Jev.",
                    "Решение принимает наша прозрачная модель, причина отсева — на экране."]),
    ("Результат", ["До 15 ранних технологий с путём от науки до рынка.", "Справка на русском, каждое утверждение проверено.",
                   "Доводы «против», игроки, связь с документами вашей компании."]),
], height=3300000)
w = 3650000
for i, (big, small) in enumerate([("2–4 мин", "новая узкая тема (замер 20.10)"), ("≈1 с", "готовые темы-примеры (рассчитаны заранее)"), ("≈30", "открытых источников: наука, рынок, веб")]):
    l = 346075 + i * (w + 275000)
    card(s, l, CARD_T + 3450000, w, CARD_H - 3450000, PINK if i == 1 else WHITE)
    text(s, l + 250000, CARD_T + 3560000, w - 500000, CARD_H - 3600000,
         [{"t": big, "size": 30, "bold": True, "color": WHITE if i == 1 else PINK, "after": 0}, {"t": small, "size": 13, "color": WHITE if i == 1 else DARK}])

# ---------- 7. Как это работает ----------
s = new_slide("Как это работает")
card(s, FULL_L, CARD_T, FULL_W, CARD_H)
pic(s, "pipeline_final.png", FULL_L + 150000, CARD_T + 200000, w=FULL_W - 300000)
text(s, FULL_L + 350000, CARD_T + 2550000, FULL_W - 700000, 2300000, [
    {"t": "Языковая модель — инструмент для текста, решение — наша модель на проверяемых фактах", "size": 16, "bold": True, "color": VIOLET, "after": 10},
    "Узкий запрос («многослойный графен», «газлифт») не размывается подтемами из словаря: сам предмет по-английски идёт первым, "
    "а растущие поднаправления берутся из научной литературы без LLM.",
    "Каждый документ проверяет Jev: описывает ли он именно эту технологию. Без трёх подтверждений кандидат остаётся «под наблюдением».",
    "Каждое обращение к моделям записано в журнал прогона: что спросили и что ответили.",
], size=14)

# ---------- 8. Чем мы лучше обычной LLM ----------
tot = lb["total"]
s = new_slide("Чем мы лучше обычной LLM")
card(s, FULL_L, CARD_T, 6900000, CARD_H)
pic(s, "llm_vs_pipeline.png", FULL_L + 150000, CARD_T + 300000, w=6600000)
card(s, FULL_L + 7100000, CARD_T, 4400000, CARD_H, LIGHT)
text(s, FULL_L + 7350000, CARD_T + 250000, 3950000, CARD_H - 400000, [
    {"t": f"{tot['llm_only_signals']} против {tot['pipeline_signals']}", "size": 34, "bold": True, "color": PINK, "after": 0},
    {"t": "подтверждённых сигналов на тех же 4 темах", "size": 14, "after": 14},
    f"Простой вопрос GigaChat «назови 15 слабых сигналов»: {round(tot['llm_only_excluded_share'] * 100)}% названий не прошли наши проверки — зрелые, общие или без доказательств.",
    "На газлифте модель предложила «ИИ для оптимизации скважин» и «квантовые вычисления» — общие слова, а не газлифт.",
    {"t": "Ранний сигнал по определению малоизвестен: его нельзя вспомнить, его нужно найти и проверить.", "bold": True, "color": VIOLET},
], size=14)

# ---------- 9. Роли моделей и почему так ----------
s = new_slide("Роли моделей и почему так")
table(s, [
    ["Задача", "Кто выполняет", "Почему"],
    ["План поиска, названия, справка", "GigaChat-2 (Сбер)", "Сильный русский текст; отечественная модель. Max проверен A/B: прибавка ниже заданного порога"],
    ["Проверка каждого документа и утверждения", "Jev 1.13.0 (TypeSafe)", "Отвечает числом, а не текстом; стабильно и дёшево; версия закреплена"],
    ["Решение «сигнал / не сигнал», место", "Наша логистическая регрессия", "Прозрачный вклад каждого признака; знаки весов совпадают со смыслом"],
    ["Источники, фильтры, лестница, игроки", "Наш код", "≈30 сборщиков, robots.txt, лимиты, кэш, правила отсева с причиной"],
], FULL_L, CARD_T, FULL_W, 2500000, [3200000, 2800000, FULL_W - 6000000], size=12)
card(s, FULL_L, CARD_T + 2700000, FULL_W, CARD_H - 2700000, LIGHT)
text(s, FULL_L + 300000, CARD_T + 2850000, FULL_W - 600000, CARD_H - 2900000, [
    {"t": "Частые вопросы", "size": 17, "bold": True, "color": VIOLET, "after": 8},
    "Почему не база RAG? Ранний сигнал — то, чего ещё нет в базе: ищем по живым источникам на момент запроса; знакомые темы — из готовых расчётов за секунду.",
    "Почему не локальная модель? Решение принимает не LLM, поэтому GPU качества не добавит; для закрытого контура локальная модель подключается настройкой.",
    "Почему не SOTA-модель? Выбор по измерению, а не по рейтингу; смена LLM почти не влияет на выдачу.",
], size=13)

# ---------- 10. Как строится оценка и место ----------
s = new_slide("Как строится оценка и место")
card(s, FULL_L, CARD_T, 5300000, CARD_H, LIGHT)
text(s, FULL_L + 250000, CARD_T + 250000, 4850000, CARD_H - 400000, [
    {"t": "Два разных числа на карточке", "size": 18, "bold": True, "color": VIOLET, "after": 10},
    "Оценка классификатора — насколько кандидат похож на слабые сигналы эталона. Это не вероятность успеха; выше 95% не показываем.",
    "Проверки доказательств: k из 5 — счёт выполненных проверок (документы, независимые источники, наука, твёрдое событие, рабочие ссылки).",
    {"t": "Балл места = min(оценка; 0,95) × (0,6 + 0,4 × релевантность)", "bold": True, "color": PINK, "after": 10},
    "Наверху порядок решает релевантность: 0,991 и 0,982 — одно и то же. «100%» и «1,00» не появляются никогда.",
    "На графике вкладов есть точка отсчёта модели: сумма сходится с итогом.",
], size=14)
card(s, FULL_L + 5500000, CARD_T, 6000000, CARD_H)
text(s, FULL_L + 5750000, CARD_T + 120000, 5500000, 400000, [{"t": "18 признаков: розовые — «за», фиолетовые — «против»", "size": 13, "bold": True, "color": VIOLET}])
pic(s, "weights_final.png", FULL_L + 5850000, CARD_T + 500000, h=CARD_H - 600000)

# ---------- 11. Качество — честно ----------
cv, rep, sl = metrics["cv5"], metrics["cv5_repeated"], metrics["slices"]["false_signal_share"]
s = new_slide("Качество — честно")
for i, (k, v) in enumerate([("F1 (5 фолдов)", num(cv["f1"])), ("F1, повтор 10×5", f"{num(rep['f1_mean'])}"), ("ROC-AUC", num(cv["roc_auc"])), ("признаков", "18")]):
    l = FULL_L + i * 1400000
    card(s, l, CARD_T, 1300000, 1350000)
    text(s, l + 60000, CARD_T + 150000, 1180000, 1200000, [{"t": v, "size": 24, "bold": True, "color": PINK, "after": 2}, {"t": k, "size": 11}])
card(s, FULL_L, CARD_T + 1500000, 5500000, CARD_H - 1500000, LIGHT)
g = gates["candidate"]
text(s, FULL_L + 250000, CARD_T + 1650000, 5100000, CARD_H - 1700000, [
    {"t": "Что важно знать о цифрах", "size": 17, "bold": True, "color": VIOLET, "after": 8},
    f"{metrics['n']} примеров: сигналы организатора и наши отрицательные. Это верхняя оценка классификатора, а не качество поиска.",
    f"Модель без GitHub и признаков с перевёрнутым знаком: все 7 заранее заданных ворот пройдены; чувствительность к шуму ответов "
    f"{num(gates['base']['noise_dlogit'], 2)} → {num(g['noise_dlogit'], 2)}.",
    "Где модель ошибается чаще — справа. Поэтому в топ кандидат попадает только с подтверждёнными документами.",
    "Качество поиска измеряем отдельно: слепая разметка карточек людьми (идёт).",
], size=13)
card(s, FULL_L + 5700000, CARD_T, 5800000, CARD_H)
text(s, FULL_L + 5950000, CARD_T + 150000, 5400000, 400000, [{"t": "Доля ложных сигналов по типам примеров", "size": 15, "bold": True, "color": VIOLET}])
pic(s, "slices.png", FULL_L + 5850000, CARD_T + 650000, w=5500000)

# ---------- 12. Машина времени ----------
main = emerg["variants"]["все индикаторы без отбора (заранее заданный вариант)"]
s = new_slide("Машина времени")
card(s, FULL_L, CARD_T, 6600000, CARD_H)
pic(s, "timemachine.png", FULL_L + 200000, CARD_T + 300000, w=6200000)
card(s, FULL_L + 6800000, CARD_T, 4700000, CARD_H, LIGHT)
text(s, FULL_L + 7050000, CARD_T + 250000, 4250000, CARD_H - 400000, [
    {"t": f"{num(emerg['base_auc'])} → {num(main['auc'])}", "size": 32, "bold": True, "color": PINK, "after": 0},
    {"t": f"{emerg['n']} тем, 5 дат среза: модель учится на одних годах и предсказывает год, которого не видела", "size": 13, "after": 12},
    f"«Импульс роста» (собственные индикаторы появления темы) добавил {num(main['delta'])} AUC; 95% интервал прибавки — "
    f"{num(main['ci95'][0])}…{num(main['ci95'][1])}. Критерий успеха был записан до прогона.",
    f"На малых темах (меньше 50 работ) базовая модель угадывала как монетка ({num(emerg['small_topics']['base_auc'])}), импульс — {num(emerg['small_topics']['young_growth_auc'])}.",
    {"t": "Неудачные варианты тоже опубликованы — на странице «Методология».", "bold": True, "color": VIOLET},
], size=13)

# ---------- 13. От сигнала к рынку ----------
s = new_slide("От сигнала к рынку")
card(s, FULL_L, CARD_T, FULL_W, 2000000)
text(s, FULL_L + 250000, CARD_T + 100000, FULL_W - 500000, 350000,
     [{"t": "Пример из живого прогона 20.10: «электролиты на основе галогенидов» (запрос «твердотельные аккумуляторы»)", "size": 13, "bold": True, "color": VIOLET}])
_lad = pic(s, "ladder.png", FULL_L, CARD_T + 420000, w=FULL_W - 600000)
_lad.left = Emu(FULL_L + (FULL_W - _lad.width) // 2)
three_cols(s, [
    ("Путь к рынку", ["9 ступеней: наука → патент → грант → стартап → раунд → пилот → контракт → серийный продукт → закупка в России.",
                      "Каждую ступень подтверждает Jev; есть дата и ссылка."]),
    ("Доводы «против»", ["Ищем сообщения о провале, отказе или массовости технологии.", "Показываем рядом с доводами «за» — без спрятанных возражений."]),
    ("Кто работает", ["Организации мира и России за 2 года (OpenAlex).", "Стартапы и компании из подтверждённых новостей и каталогов."]),
], top=CARD_T + 2150000, height=CARD_H - 2150000, size=13, mid_light=True)

# ---------- 14. Для аналитика ----------
s = new_slide("Для аналитика банка")
items = [("Под вашу компанию", "Загрузите стратегию или ТЗ — система покажет связанные сигналы и абзац документа. Без LLM, документ не сохраняется."),
         ("Подписка на тему", "Пересчёт раз в неделю: что появилось, что выпало, что усилилось (новый патент, раунд, пилот)."),
         ("Прогноз с проверкой", "Прогноз по каждому сигналу фиксируется на дату и через полгода проверяется сам — метрику нельзя подогнать."),
         ("Выдача по мере проверки", "Подтверждённые кандидаты видны уже во время расчёта; готовые темы — за секунду с датой расчёта.")]
for i, (h, d) in enumerate(items):
    col, row = i % 2, i // 2
    l, t = FULL_L + col * 5850000, CARD_T + row * 2550000
    card(s, l, t, 5650000, 2400000, LIGHT if (i in (0, 3)) else WHITE)
    text(s, l + 250000, t + 220000, 5150000, 2000000, [{"t": h, "size": 19, "bold": True, "color": PINK if i in (0, 3) else VIOLET, "after": 10}, d], size=14)

# ---------- 15. Живые запросы ----------
s = new_slide("Живые запросы: любые отрасли")
table(s, [
    ["Запрос", "Отрасль", "Время", "Сигналов", "Примеры"],
    ["технология многослойного графена", "материалы", "3:56", "7", "ромбоэдрический графен; дробный аномальный эффект Холла"],
    ["твердотельные аккумуляторы", "энергетика", "5:39", "7", "галогенидные и высокоэнтропийные электролиты"],
    ["жидкостная биопсия", "медицина", "4:52", "5", "spectroscopic liquid biopsy; ранняя диагностика нескольких видов рака"],
    ["аддитивное производство титановых сплавов", "машиностроение", "3:51", "4", "легирование in situ при 3D-печати"],
    ["цифровые двойники месторождений", "нефтегаз", "3:35", "3", "петрофизическое моделирование каротажа"],
    ["газлифт в газоконденсатных скважинах", "нефтегаз", "2:12", "1 + 3 под наблюдением", "оптимизация газлифта на основе машинного обучения"],
], FULL_L, CARD_T, FULL_W, 3300000, [3300000, 1600000, 900000, 1500000, FULL_W - 7300000], size=12)
card(s, FULL_L, CARD_T + 3500000, FULL_W, CARD_H - 3500000, LIGHT)
text(s, FULL_L + 300000, CARD_T + 3620000, FULL_W - 600000, CARD_H - 3700000, [
    "Прогоны 20.10 на итоговом коде, по одному без очереди. Требование ТЗ — до 20 минут.",
    "Мало подтверждений — кандидат честно остаётся «под наблюдением», а не попадает в топ ради числа 15.",
], size=13)

# ---------- 16. Конкуренты ----------
s = new_slide("Сравнение с финалистами")
table(s, [
    ["", "Мы", "МакВоркеры", "Квадрицепс", "zama / Pelican"],
    ["Новая тема", "2–4 мин", "≈3,3 мин", "≈5 мин", "21–37 мин на стенде"],
    ["Готовые темы", "11, ≈1 с, раскрыто", "186 (84 со слабой разметкой)", "—", "история отчётов"],
    ["Инфраструктура", "1 сервер без GPU", "архив 5,4 ГБ", "≈20 контейнеров, GPU", "десятки ГБ + GPU"],
    ["Решение «сигнал / нет»", "своя регрессия, знаки проверены", "правила + калибровка", "классификатор", "модель роста"],
    ["Путь к рынку и «против»", "да, подтверждено Jev", "шкала прессы", "гипотезы пилотов", "устойчивость сигнала"],
    ["Замер «только LLM»", "4 против 22", "—", "—", "—"],
], FULL_L, CARD_T, FULL_W, 3600000, [2700000, 2300000, 2200000, 2100000, FULL_W - 9300000], size=12)
text(s, FULL_L, CARD_T + 3800000, FULL_W, 900000, [
    {"t": "Данные соперников — из их репозиториев и стендов на 19.10; метрики качества у команд посчитаны на разных выборках и напрямую не сравнимы.", "size": 12, "color": WHITE},
], size=12)

# ---------- 17. Честные ограничения ----------
s = new_slide("Честные ограничения")
lims = [
    ("Метрики классификатора", "посчитаны на нашей выборке; качество поиска меряем слепой разметкой людей — она идёт."),
    ("Нишевые отрасли", "мало открытых источников: в газлифте 1 сигнал и 3 «под наблюдением»."),
    ("Широкие запросы", "иногда дают общие названия; лучше работают узкие формулировки."),
    ("Патенты и закупки", "ищутся веб-поиском по фразе — пустая ступень не доказывает отсутствие."),
    ("Бесплатные квоты", "OpenAlex и Brave ограничены в сутки и месяц; при сбое прогон помечается и не выдаётся повторно."),
    ("Прогноз с проверкой", "первые результаты — через 180 дней; сейчас виден механизм."),
]
for i, (h, d) in enumerate(lims):
    col, row = i % 2, i // 2
    l, t = FULL_L + col * 5850000, CARD_T + row * 1650000
    card(s, l, t, 5650000, 1520000, WHITE)
    text(s, l + 250000, t + 150000, 5150000, 1300000, [{"t": h, "size": 16, "bold": True, "color": PINK, "after": 6}, d], size=13)

# ---------- 18. Эффект и развитие ----------
s = new_slide("Эффект и развитие")
three_cols(s, [
    ("Сейчас", ["Запрос из любой отрасли → до 15 сигналов за 2–4 минуты", "Путь к рынку, доводы «против», игроки", "Проверка каждого утверждения справки", "Docker, один сервер без GPU"]),
    ("Далее", ["Подписки и прогнозы по расписанию", "Патенты EPO и Lens, открытые данные госзакупок", "Накопительный архив отраслевых новостей", "Дообучение на оценках аналитиков"]),
    ("Внедрение", ["Интеграция в ИИ-аналитику банка", "Закрытый контур: локальная модель", "Экспорт для техкомитетов: Excel, Markdown", "Стоимость запроса — рубли"]),
], height=3600000)
card(s, FULL_L, CARD_T + 3750000, FULL_W, 850000, PINK)
text(s, FULL_L + 300000, CARD_T + 3830000, FULL_W - 600000, 800000,
     [{"t": "От дней ручного поиска — к минутам: ранние технологии с проверяемым путём к рынку", "size": 18, "bold": True, "color": WHITE}])
text(s, FULL_L, CARD_T + CARD_H + 60000, FULL_W, 400000,
     [{"t": "Код: github.com/Krackenhell/lct-2026-weak-signals (ветка final-improvements)", "size": 14, "bold": True, "color": WHITE}])

prs.save(str(OUT))
print("saved", OUT, "slides:", len(prs.slides))
