"""Русские названия технологий: глоссарий, склейка дефисами, кальки (примеры — реальные ответы GigaChat из базы)."""
import pytest

from app.llm.terms import check_name_ru, normalize_name_ru


@pytest.mark.parametrize("en, ru, expected", [
    ("prompt hardening", "закаливание подсказок", "защита промптов от атак"),  # пример экспертов финала
    ("Embodied AI", "Обусловленный ИИ", "воплощённый ИИ"),
    ("embodied artificial intelligence", "телесная искусственная интеллекуальная агентность", "воплощённый ИИ"),
    ("artificial intelligence in industrial automation", "искусственный-интеллект-в-промышленной-автоматизации",
     "искусственный интеллект в промышленной автоматизации"),
    ("low-power AI accelerators", "низкопотребляющие ускорители ИИ для устройств на краях", "низкопотребляющие ускорители ИИ для устройств на периферии"),
    ("industrial foundation models", "промышленные основополагающие модели ИИ", "промышленные фундаментальные модели ИИ"),
    ("agent swarms", "агентские рои", "агентные рои"),
    ("prompt leakage defense", "защита от утечки подсказок", "защита от утечки промптов"),
    ("deep learning predictive maintenance", "глубинное-обученое прогнозирование отказов", "deep learning predictive maintenance"),
    ("AI-powered companion robots", "роботы-компаньоны с поддержкой ИИ", "роботы-компаньоны с поддержкой ИИ"),  # нормальный дефис не трогаем
    ("smart contract", "умный контракт", "смарт-контракт"),
    ("graph continuous networks", "графовые-непрерывные-сети", "графовые непрерывные сети"),
    ("edge silicon", "Специализированный edge-кремний под инференс VLA-моделей", "Специализированный edge-кремний под инференс VLA-моделей"),
    ("quantum-inspired compression", "Квантово-инспирированное сжатие моделей", "Квантово-инспирированное сжатие моделей"),
    ("compute-in-memory", "Аналоговые compute-in-memory чипы", "Аналоговые compute-in-memory чипы"),
    ("solid-state lithium-ion batteries", "Твердотельные литий-ионные батареи", "Твердотельные литий-ионные батареи"),
    ("intrusion control systems", "системы-интрузионного-контроля", "системы интрузионного контроля"),
    ("small modular reactors", "маломодульные-ядерные-реакторы", "маломодульные ядерные реакторы"),
    ("adversarial attacks on ML", "адversarial-атаки-на-машинное-обучение", "adversarial attacks on ML"),
    ("federated learning", "", "федеративное обучение"),
    ("quantum dots", "", ""),
])
def test_normalize_name_ru(en, ru, expected):
    assert normalize_name_ru(en, ru) == expected


@pytest.mark.parametrize("en, ru, expected", [
    ("fractional chern insulator", "фракционный чирн-изолятор", "дробный черновский изолятор"),  # глоссарий (реальный ответ 19.10)
    ("twisted multilayer graphene", "скрученный мультиграфен", "скрученный многослойный графен"),
    ("evaporation methods for perovskite-silicon tandems", "Перовскит-силиконовые тандемные элементы", "Перовскит-кремниевые тандемные элементы"),
    ("silicone microfluidic chips", "силиконовые микрофлюидные чипы", "силиконовые микрофлюидные чипы"),  # silicone — действительно силикон
    ("fractional quantum anomalous hall effect", "фракционный квантовый аномальный эффект Холла", "дробный квантовый аномальный эффект Холла"),
    ("high chern insulators", "высокие чирновские инсуляторы", "черновские изоляторы с большим числом Черна"),  # живой прогон 19.10
    ("chern insulators in moire graphene", "чирновские инсуляторы в муаровом графене", "черновские изоляторы в муаровом графене"),
    ("3d printed microfluidic chips", "3D-печатные микрожидкостные чипы", "3D-печатные микрофлюидные чипы"),
    ("microfluidic live-cell imaging", "микрожидкостное живое клеточное изображение", "микрофлюидная визуализация живых клеток"),
    ("oil and gas digital twin", "цифровой_двойник_нефтегазовой_отрасли", "цифровой двойник нефтегазовой отрасли"),  # живой прогон 20.10
    ("transdimensional chern insulators", "трансмерные черновые изоляторы", "трансмерные черновские изоляторы"),
    ("ml-based gas lift optimization", "оптимизация газового подъема на основе машинного обучения", "оптимизация газлифта на основе машинного обучения"),
    ("tumor educated platelets", "туморо-образованные тромбоциты", "tumor educated platelets"),
])
def test_conditional_calques(en, ru, expected):
    assert normalize_name_ru(en, ru) == expected


def test_all_solid_state_is_not_for_all():
    """all-solid-state — «полностью твердотельный», а не «для всех твердотельных» (прогон 20.10)."""
    ru, why = check_name_ru("halide electrolytes for all-solid-state batteries", "галогенидные электролиты для всех твёрдотельных аккумуляторов")
    assert ru == "галогенидные электролиты для полностью твердотельных аккумуляторов" and why is None


def test_text_fixes_in_dossier():
    from app.llm.terms import fix_text_ru

    assert fix_text_ru("Микрожидкостные устройства и 3д-печать") == "Микрофлюидные устройства и 3D-печать"
    assert check_name_ru("3d resin printing", "резиновая 3д-печать")[0] == "3D-печать фотополимерными смолами"


@pytest.mark.parametrize("en,ru,expected", [
    ("moire fractional chern insulators y", "мозаичные дробные черновский изоляторы", "муаровые дробные черновские изоляторы"),
    ("superconductivity in multilayer graphene x", "сверхпроводимость в мультислоевом графене", "сверхпроводимость в многослойном графене"),
    ("generalized wigner crystal lattices", "обобщённые кристаллы винера", "обобщённые кристаллы Вигнера"),
])
def test_graphene_physics_calques(en, ru, expected):
    """Кальки из прогона «многослойный графен» 20.10."""
    assert check_name_ru(en, ru)[0] == expected
