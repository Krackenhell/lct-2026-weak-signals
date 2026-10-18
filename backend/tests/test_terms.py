"""Русские названия технологий: глоссарий, склейка дефисами, кальки (примеры — реальные ответы GigaChat из базы)."""
import pytest

from app.llm.terms import normalize_name_ru


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
