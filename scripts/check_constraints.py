#!/usr/bin/env python3
"""Контроль ограничений кейса (MET-12): только модели Cloud.ru, никаких SDK и ключей зарубежных провайдеров.

Проверяет: (1) requirements без запрещённых SDK; (2) импорты чужих провайдеров в коде;
(3) переменные окружения чужих провайдеров; (4) жёстко зашитые адреса — только разрешённые хосты.
Вывод: «ограничения кейса: соблюдены» и код 0 либо список нарушений и код 1.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SDK = {'openai', 'anthropic', 'google-generativeai', 'langchain-openai', 'cohere', 'mistralai'}
FORBIDDEN_ENV = ('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_ORG', 'ANTHROPIC_API_KEY', 'GOOGLE_API_KEY',
                 'GEMINI_API_KEY', 'AZURE_OPENAI', 'COHERE_API_KEY', 'MISTRAL_API_KEY')
ALLOWED_HOSTS = ('foundation-models.api.cloud.ru', 'hub.gigaschool.ru', '127.0.0.1', 'localhost', '0.0.0.0', 'json-schema.org', 'schemas.openxmlformats.org')  # OOXML-namespace константа формата, не сеть  # 0.0.0.0 — прокси-заглушка песочницы, json-schema.org — ссылка на спецификацию формата


def main() -> int:
    problems: list[str] = []
    # 1. Зависимости
    for req in sorted(ROOT.glob('requirements*.txt')):
        for i, line in enumerate(req.read_text(encoding='utf-8').splitlines(), 1):
            name = re.split(r'[=<>!;\[ ]', line.strip(), maxsplit=1)[0].lower()
            if name in FORBIDDEN_SDK:
                problems.append(f'{req.name}:{i}: запрещённый пакет «{name}»')
    # 2. Импорты и 3. переменные чужих провайдеров — только в рабочем коде
    me = Path(__file__).resolve()
    py_files = [p for p in sorted(ROOT.glob('src/**/*.py')) + sorted(ROOT.glob('scripts/**/*.py')) if p.resolve() != me]  # сам скрипт содержит имена запрещённых переменных по определению
    for py in py_files:
        rel = py.relative_to(ROOT)
        for i, line in enumerate(py.read_text(encoding='utf-8').splitlines(), 1):
            code = line.split('#', 1)[0]
            if (m := re.search(r'^\s*(?:import|from)\s+(openai|anthropic|google\.generativeai|cohere|mistralai)\b', code)):
                problems.append(f'{rel}:{i}: импорт чужого провайдера «{m.group(1)}»')
            if any(env in code for env in FORBIDDEN_ENV):
                problems.append(f'{rel}:{i}: переменная окружения чужого провайдера: {line.strip()[:80]}')
    # 4. Жёстко зашитые http(s)-адреса в рабочем коде — только разрешённые хосты
    for py in sorted(ROOT.glob('src/**/*.py')):
        rel = py.relative_to(ROOT)
        for i, line in enumerate(py.read_text(encoding='utf-8').splitlines(), 1):
            code = line.split('#', 1)[0]
            if 'LLM_BASE_URL' in code or 'CLOUDRU_BASE_URL' in code or 'example' in code:
                continue  # адрес берётся из окружения или это пример из докстринга
            for m in re.finditer(r'https?://([^/\'"\s]+)', code):
                host = m.group(1).lower().removeprefix('www.').split(':', 1)[0]
                if not any(host == h or host.endswith('.' + h) for h in ALLOWED_HOSTS):
                    problems.append(f'{rel}:{i}: адрес вне разрешённых хостов: {m.group(0)}')
    if problems:
        print('Ограничения кейса: НАРУШЕНЫ')
        for p in problems:
            print(f'  - {p}')
        return 1
    print('Ограничения кейса: соблюдены (модели только Cloud.ru, чужих SDK, ключей и адресов нет)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
