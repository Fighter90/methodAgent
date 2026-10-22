# Отчёт качества и приёмка слайдов автопрогона

Префикс требований: `SPEC-Q`. Код: `scripts/quality_report.py`, `scripts/autorun.py` (чеки слайдов чек-листа). Тесты: `tests/test_quality_report.py`, `tests/test_autorun_checks.py`.

## Назначение

`quality_report.py` перегенерирует `docs/reports/quality.md` фактическими числами локальной проверки (MET-8; аудит 22.10: MET-57/R13). Провал обязательной проверки должен быть виден и в отчёте, и в коде выхода процесса: наличие «done» в выводе или отсутствие латинского FAIL — не успех, учитываются код возврата дочернего процесса и его сводка. Чеки слайдов автопрогона (аудит 22.10: MET-58/R14) принимают слайды только при полноте по заявленным темам и принадлежности лекций своим модулям комплекта.

## Требования

| ID | Требование | Источник | Тест |
|---|---|---|---|
| SPEC-Q-01 | WHEN обязательная проверка отчёта провалена — `pytest` вернул ненулевой код или в его сводке «N failed»/«N error», автопрогон `scripts/autorun.py` вернул ненулевой код или не напечатал финальный маркер «все кейсы и выгрузки прошли», THEN THE SYSTEM SHALL записать в `docs/reports/quality.md` колонку «Статус» со значением FAIL у проваленной проверки, итог «ЕСТЬ ПРОВАЛЫ», напечатать «ОТЧЁТ: ЕСТЬ ПРОВАЛЫ» и завершиться с кодом 1; IF все обязательные проверки прошли, THEN THE SYSTEM SHALL записать PASS и завершиться с кодом 0. | Доп. (аудит MET-57/R13) | `test_quality_report.py::test_build_report_data_marks_failures`, `test_quality_report.py::test_build_report_data_happy_path`, `test_quality_report.py::test_pytest_verdict_reads_failures`, `test_quality_report.py::test_autorun_verdict_reads_markers`, `test_quality_report.py::test_main_exit_code_and_report` |
| SPEC-Q-02 | WHEN автопрогон принимает слайды кейса (кейс 1 — занятия 1 и 2; кейс 3 — каждая тема модуля с pandas по плану из ответа `kit.modules`; кейс 5 — появившиеся лекции со слайдами), THE SYSTEM SHALL засчитать чек только если у каждой заявленной темы есть лекция с непустыми слайдами и `module_id` этой лекции совпадает с модулем темы; IF лекция со слайдами принадлежит модулю вне комплекта или её тема отсутствует в плане, THEN THE SYSTEM SHALL провалить чек слайдов этого кейса. | Доп. (аудит MET-58/R14), SPEC-API-30 | `test_autorun_checks.py::test_case3_slides_check_requires_every_pandas_topic`, `test_autorun_checks.py::test_case1_slides_must_belong_to_own_module`, `test_autorun_checks.py::test_case5_slides_must_belong_to_own_module` |

## Вне области

Генерация и ремонт слайдов (`workflow.ensure_module_slides`, навык content) — в `specs/agent-workflow.md` и `specs/skill-content.md`; структурная проверка файлов выгрузок — SPEC-API-30 в `specs/api.md`; содержимое разделов отчёта (живой замер, синтетические объёмы) — информационное и не специфицируется.
