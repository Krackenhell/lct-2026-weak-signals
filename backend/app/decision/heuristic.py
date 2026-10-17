"""Офлайн-запасной вариант decision-модели: прозрачные словарные правила.

Используется, когда нет доступа ни к Jev, ни к локальному Kev (разработка, тесты, сбой сети).
Качество ниже, поэтому в журнале и интерфейсе такие ответы явно помечаются.
"""
import re

from app.decision.base import DecisionResult, Timer

LEX = {
    "mass_adoption": r"widely (used|adopted|deployed)|mainstream|ubiquitous|billions? of users|industry-wide|de facto|commonplace|millions of (users|devices)|market leader",
    "market_leaders": r"market share|dominant|market leader|leading vendors|incumbent|billion market|market size",
    "standard": r"\bstandard\b|\bprotocol\b|\biso ?\d+|specification|\bregulation\b|\brfc ?\d+",
    "early_stage": r"prototype|proof[- ]of[- ]concept|pilot|we propose|novel|preliminary|early[- ]stage|first (demonstration|deployment)|seed|series a|stealth|emerging|testbed|feasibility",
    "independent": r"universit|institute|laborator|consortium|researchers|et al",
    "hype": r"revolutionar|game[- ]chang|disrupt|unprecedented|next[- ]generation|world'?s first|announces|press release|leading provider|cutting[- ]edge",
    "novelty": r"novel|new|emerging|first|recent|propose|introduc",
    "benefit": r"reduc|improv|faster|lower cost|higher accuracy|efficien|enabl|outperform|saving",
}

# Самое твёрдое событие: от высшего уровня к низшему (уровни как в questions.EVENT_LEVELS).
EVENT_LEX = [
    (6, r"series [abc]\b|seed round|raised \$|funding round|acquir|spin[- ]?off|венчур|раунд"),
    (5, r"\breleased?\b|launch(es|ed)?\b|open[- ]sourced?|general availability|available on github"),
    (4, r"\bpilot|field trial|deployed at|in production at|trial with|пилот"),
    (3, r"\bgrant\b|funded by|\bnsf\b|horizon europe|\bdarpa\b|грант"),
    (2, r"prototype|proof[- ]of[- ]concept|demonstrat|testbed|прототип"),
    (1, r"\bwe propose|\bpaper\b|preprint|arxiv|study|we present"),
]
STOP = {"with", "from", "that", "this", "based", "using", "for", "and", "the", "new", "approach", "system", "systems", "model", "models"}


def _words(s: str, n: int = 4) -> set[str]:
    return {w for w in re.findall(rf"\w{{{n},}}", s.lower()) if w not in STOP}


def _items(state: str) -> dict[int, str]:
    out = {}
    for line in state.splitlines():
        m = re.match(r"^\[(\d+)\]\s*(.*)", line)
        if m:
            out[int(m.group(1))] = m.group(2).lower()
    return out


BROAD = {"artificial intelligence", "machine learning", "deep learning", "robotics", "fintech", "blockchain", "cybersecurity", "internet of things", "edge computing", "big data", "generative ai", "large language model", "sustainability"}


def _rate(pattern: str, text: str, scale: float) -> float:
    hits = len(re.findall(pattern, text, flags=re.I))
    return max(0.05, min(0.95, 0.15 + hits / scale))


class HeuristicDecision:
    provider = "heuristic"
    model = "rules-v1"

    async def ask(self, state: str, questions: dict) -> DecisionResult:
        with Timer() as t:
            subject = (re.search(r"SUBJECT: (.*)", state) or [None, ""])[1].strip().lower()
            topic = (re.search(r"TOPIC OF INTEREST: (.*)", state) or [None, ""])[1].strip().lower()
            # Оцениваем только текст доказательств: слова из названия («protocol», «standard») не должны влиять.
            text = state.lower().split("evidence:", 1)[-1]
            n_ev = max(len(re.findall(r"^\[\d+\]", state, flags=re.M)), 1)
            answers = {}
            for qid, q in questions.items():
                if qid == "specific_tech":
                    words = len(subject.split())
                    v = 0.2 if subject in BROAD else min(0.9, 0.35 + 0.15 * words)
                    answers[qid] = {"type": "noul", "value": v}
                elif qid in LEX:
                    answers[qid] = {"type": "noul", "value": _rate(LEX[qid], text, 2.0 * n_ev)}
                elif qid == "maturity":
                    early = _rate(LEX["early_stage"], text, 2.0 * n_ev)
                    mass = _rate(LEX["mass_adoption"], text, 2.0 * n_ev)
                    v = max(0.0, min(1.0, 0.45 + 0.6 * (mass - early)))
                    answers[qid] = {"type": "score", "value": v, "level": v * 5}
                elif qid in ("relevance", "relevance_query"):
                    # Правила не сопоставляют русский запрос с английскими текстами — оба вопроса оцениваются по теме.
                    tw = {w for w in re.findall(r"\w{4,}", topic)}
                    hit = sum(1 for w in tw if w in text)
                    v = 0.4 + 0.6 * (hit / max(len(tw), 1))
                    answers[qid] = {"type": "score", "value": min(v, 1.0), "level": min(v, 1.0) * 3}
                elif qid == "event":
                    level = next((lv for lv, pat in EVENT_LEX if re.search(pat, text, flags=re.I)), 0)
                    answers[qid] = {"type": "score", "value": level / 6, "level": float(level)}
                elif qid.startswith("doc_"):
                    # Документ подтверждает предмет, если в нём есть большая часть значимых слов названия.
                    sw = _words(subject)
                    item = _items(state).get(int(qid[4:]), "")
                    share = sum(1 for w in sw if w in item) / max(len(sw), 1)
                    answers[qid] = {"type": "noul", "value": 0.85 if share >= 0.6 else 0.5 if share >= 0.34 else 0.1}
                elif qid.startswith("claim_"):
                    # Утверждение подтверждено, если его значимые слова встречаются в доказательствах.
                    statement = q.get("instructions", "").split("STATEMENT:", 1)[-1]
                    cw = _words(statement, 5)
                    share = sum(1 for w in cw if w in text) / max(len(cw), 1)
                    answers[qid] = {"type": "noul", "value": round(min(0.95, 0.1 + share), 3)}
                else:
                    answers[qid] = {"type": q.get("type", "noul"), "value": 0.5}
        return DecisionResult(answers, self.provider, self.model, t.ms)
