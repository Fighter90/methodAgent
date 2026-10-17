---
name: export
description: Выгрузка программы .docx по шаблону АЦР, слайдов .pptx, тестов GIFT и Moodle XML, комплекта JSON
model_role: none
temperature: 0
max_tokens: 0
timeout_s: 20
retries: 1
input: schema_in.json
output: schema_out.json
---
Выполняется кодом (src/app/export). Реквизиты приказа, ФИО преподавателей и подписи остаются полями для заполнения.
