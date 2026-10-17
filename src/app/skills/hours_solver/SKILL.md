---
name: hours_solver
description: Часы по модулям, темам и видам работы; календарь и конфликты
model_role: none
temperature: 0
max_tokens: 0
timeout_s: 2
retries: 0
input: schema_in.json
output: schema_out.json
---
Выполняется кодом (src/app/solver): метод наибольших остатков, практика закрывает строку,
режим «стажировка» — все часы модулей в СРС. Одинаковый вход даёт одинаковый результат.
