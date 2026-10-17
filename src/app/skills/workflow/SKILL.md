---
name: workflow
description: Конечный автомат состояний программы, переходы, блокировки и журнал
model_role: none
temperature: 0
max_tokens: 0
timeout_s: 1
retries: 0
input: schema_in.json
output: schema_out.json
---
Состояния: draft → questions → skeleton → skeleton_approved → generating → kit_ready → on_review → on_approval → approved
(возвраты: returned). Генерация содержания запускается только после утверждения каркаса методистом или правилом
auto-approve в режиме auto. Состояние сохраняется после каждого шага.
