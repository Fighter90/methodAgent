"""Эффект программы для защиты: часы методиста и стоимость генерации (SPEC-API-24)."""

import os

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from fastapi.testclient import TestClient  # noqa: E402


def test_autorun_reports_effect(tmp_path, monkeypatch) -> None:
    """SPEC-API-24: ответ автопрогона содержит effect: ручная трудоёмкость, вычитка, сэкономленные часы, стоимость и рубли за сэкономленный час."""
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        j = c.post('/api/v1/programs?mode=auto', json={'request': 'Программа повышения квалификации «Анализ данных на Python», 72 часа'}).json()
    e = j['effect']
    assert e['manual_hours'] > e['saved_hours'] > 0
    assert abs(e['manual_hours'] - e['review_hours'] - e['saved_hours']) < 0.11
    assert e['breakdown_hours']['lectures'] > 0 and e['breakdown_hours']['questions'] > 0
    assert e['generation_rub'] == j['tokens']['cost_rub'] and 'method' in e
