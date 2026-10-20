"""Применяет текущий глоссарий и исправления калек к уже сохранённым прогонам — без пересчёта и без вызова моделей.

Нужен после пополнения глоссария (app/llm/terms.py): готовые результаты тем-примеров на стенде показывают исправленные
русские названия и справки сразу, а не после следующего предрасчёта. Названия организатора (база отслеживания) не трогаются.

    python -m app.ml.renormalize_names            # все прогоны
    python -m app.ml.renormalize_names 32 33 34   # выбранные
"""
import sys

from app.db import SessionLocal
from app.llm.terms import check_name_ru, fix_text_ru
from app.models import Candidate, Document, Run


def renormalize(run_ids: list[int] | None = None) -> dict:
    changed_names = changed_texts = 0
    with SessionLocal() as s:
        q = s.query(Run)
        if run_ids:
            q = q.filter(Run.id.in_(run_ids))
        for run in q:
            for c in s.query(Candidate).filter_by(run_id=run.id):
                methods = (c.contributions or {}).get("methods", [])
                if c.name_ru and "watchlist" not in methods:
                    ru, why = check_name_ru(c.name, c.name_ru, run.query)
                    new = ru if ru and ru != c.name and not why else c.name_ru
                    if new != c.name_ru:
                        c.name_ru, changed_names = new, changed_names + 1
                if c.dossier:
                    fixed = {k: fix_text_ru(v) if isinstance(v, str) else v for k, v in c.dossier.items()}
                    if fixed != c.dossier:
                        c.dossier, changed_texts = fixed, changed_texts + 1
            for d in s.query(Document).filter(Document.run_id == run.id, Document.summary_ru.isnot(None)):
                fixed = fix_text_ru(d.summary_ru)
                if fixed != d.summary_ru:
                    d.summary_ru, changed_texts = fixed, changed_texts + 1
        s.commit()
    return {"names": changed_names, "texts": changed_texts}


if __name__ == "__main__":
    print(renormalize([int(x) for x in sys.argv[1:]] or None))
