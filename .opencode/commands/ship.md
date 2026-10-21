---
description: Закоммитить от имени автора, запушить в main и выкатить на стенд
---
Выполни по порядку, ничего не спрашивая, если проверки зелёные:

1. Запусти `/check`; при ошибках исправь их.
2. Обнови `docs/changelog.md` и `wiki/История-изменений.md` (новая версия, по-русски, что изменилось для пользователя); при изменении требований обнови `specs/*.md`, `docs/tz-compliance.md`, `wiki/Соответствие-ТЗ.md`.
3. Коммит строго от автора, без строк Co-Authored-By и без упоминаний ИИ:
   `git add -A && git -c user.name="Емельянов Сергей Борисович" -c user.email="sbemelyanov@edu.hse.ru" commit -m "<по-русски, что изменилось>"`
4. Проверь окно: с 06:00 до 10:00 МСК push закрыт (проверка жюри). В это время только коммить локально и сообщи об этом.
5. `git push origin main` (без --force).
6. Деплой на ВМ:
   `ssh -J jump@84.54.59.198 tochka-sborki-2026-team-098@10.250.0.101 'cd ~/project && git pull --ff-only origin main && chmod +x scripts/deploy_vm.sh && ./scripts/deploy_vm.sh'`
   Пароли не печатай и не вводи за пользователя: если ssh просит пароль, попроси пользователя ввести его самому.
7. Проверь стенд: `curl -fsS https://tochka-sborki-2026-team-098.hub.gigaschool.ru/health` и в контейнере
   `ssh ... 'cd ~/project && docker compose exec -T app python scripts/e2e_regression.py --base http://127.0.0.1:8000'`.

Доложи: хеш коммита, статус push, версию на /health, итог e2e. $ARGUMENTS
