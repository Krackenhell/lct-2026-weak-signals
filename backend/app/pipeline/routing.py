"""Маршрут источников по профилю запроса — детерминированное правило, без LLM.

Зачем. Для наук о жизни, материалов и энергетики arXiv почти пуст, а ML-источники (Hugging Face Papers, OpenReview)
дают шум; для ИИ — наоборот. Профиль определяется регулярными выражениями по запросу и плану: OpenAlex group_by
и поля от GigaChat не используем — такой маршрутизатор отправлял финтех в «industry services».
GitHub и Hacker News не отключаются ни в одном профиле: это признаки классификатора.
"""
import re

from app.config import get_settings

LIFE_MED = (r"медиц|здрав|биотех|биолог|фарм|генн|геном|белк|клиник|диагност|вакцин|биосенс|микрофлюид|биопечат|орган\w* на чипе|лаборатори\w* на чипе|"
            r"health|medic|biotech|\bbio|pharma|gene|protein|clinic|drug|patholog|vaccin|biosens|diagnos|crispr|microflu|"
            r"lab.on.a.chip|organ.on|point.of.care|bioprint")
MATERIALS = r"графен|graphene|mxene|перовск|perovskit|катализ|catalys|полимер|polymer|композит|composite|нано|nano|материал|material"
ENERGY = r"аккумул|батар|battery|batteries|solar|солнечн|водород|hydrogen|электролиз|electroly|fuel cell|топливн|энерг|energy|нефт|газлифт|термояд|oil|gas lift|fusion"
AI = r"\bии\b|искусственн|нейросет|машинн|\bai\b|artificial intelligence|\bllm|\bml\b|робот|robot|агент|agent|edge|вычисл|comput|данн|\bdata\b"

LABELS = {"life_med": "науки о жизни", "materials": "материалы", "energy": "энергетика", "software": "ИТ и ИИ"}


def profile(query: str, plan: dict | None = None) -> str:
    """life_med | materials | energy | software. Сначала смотрим на сам запрос, затем на английский термин плана."""
    for text in (query or "", " ".join(str((plan or {}).get(k) or "") for k in ("topic_en", "core_term"))):
        for name, pat in (("life_med", LIFE_MED), ("materials", MATERIALS), ("energy", ENERGY)):
            if re.search(pat, text, re.I):
                return name
    return "software"


def is_ai(query: str, plan: dict | None = None) -> bool:
    return bool(re.search(AI, f"{query} {(plan or {}).get('topic_en', '')}", re.I))


def route(query: str, plan: dict | None = None) -> dict:
    """Какие источники подключать: Europe PMC (корпус и доказательства), ML-источники по кандидату."""
    on = get_settings().routing
    prof = profile(query, plan)
    ai = is_ai(query, plan)
    r = {
        "profile": prof, "label": LABELS[prof], "enabled": on,
        "europepmc_corpus": prof in ("life_med", "materials", "energy") if on else prof == "life_med",
        "europepmc_evidence": on and prof == "life_med",
        "ml_evidence": ai or not on,
    }
    parts = []
    if r["europepmc_corpus"]:
        parts.append("+ Europe PMC")
    if r["europepmc_evidence"]:
        parts.append("Europe PMC по каждому кандидату")
    if not r["ml_evidence"]:
        parts.append("без Hugging Face Papers и OpenReview")
    r["text"] = f"{LABELS[prof]}" + (": " + ", ".join(parts) if parts else "")
    return r
