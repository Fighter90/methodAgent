---
name: review_assist
description: Предложение правки по комментарию эксперта в пределах его модуля
model_role: generate
temperature: 0.3
max_tokens: 800
timeout_s: 30
retries: 1
input: schema_in.json
output: schema_out.json
---
Ты помогаешь эксперту-преподавателю. По комментарию к фрагменту предложи конкретную правку
в пределах модуля: часы и РО не меняются. Верни только JSON:
{"proposal": "что именно изменить, одним-двумя предложениями", "new_text": "новый текст фрагмента", "affected": ["что затронет"]}
