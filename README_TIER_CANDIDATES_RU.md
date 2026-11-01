# COSTARO — отдельные товары для трёх уровней цен (01.11.2026)

Мониторинг расширен **только для двух материалов**: финишной шпаклёвки
(`finishPutty`, упаковка 8 кг) и интерьерной краски (`interiorPaint`, 7 кг).
Для каждого добавлены отдельные товары-образцы на уровни «Бюджет»,
«Стандарт», «Премиум». Источники выбраны по совпадающей фасовке, типу
применения и конкретным артикулам на сайтах магазинов Молдовы.

## Шпаклёвка, готовая, 8 кг

| Уровень-кандидат | Товар | Macons | Другой сайт | Цена в COSTARO |
|---|---|---|---|---:|
| Бюджет | Meșterul Manole 8 кг | [167 MDL, код 543](https://macons.md/glet-mesterul-manole-8kg) | [Domic, 167 MDL, код 240](https://domic.md/ro/glet-mesterul-manole-8kg/91) | 167 MDL |
| Стандарт | B-62 SATROC 8 кг | [191 MDL, код 513](https://macons.md/glet-b-62-satroc-8kg) | [ObraMag, 191 MDL, код 370035](https://obramag.md/product/glet-finisare-acril-b-62-satroc-8kg) | 191 MDL |
| Премиум | SATROC 8 кг | [234 MDL, код 518](https://macons.md/glet-satroc-8kg) | [ObraMag, 234 MDL, код 6000120](https://obramag.md/product/glet-finisare-acril-satroc-8kg) | 234 MDL |

## Краска для внутренних работ, 7 кг

| Уровень-кандидат | Товар | Macons | Другой сайт | Цена в COSTARO |
|---|---|---|---|---:|
| Бюджет | ROMANIȚA 7 кг | [214 MDL, код 588](https://macons.md/vopsea-romanita-7kg) | [Domic, 214 MDL, код 285](https://domic.md/ro/vopsea-romanita-7kg/136) | 214 MDL |
| Стандарт | EUROTON LAV 7 кг | [325 MDL, код 583](https://macons.md/vopsea-euroton-lav-7kg) | [ObraMag, код 350014](https://obramag.md/product/vopsea-interior-supraten-euroton-lav-7kg) | 341 MDL |
| Премиум | SANSIRO 7 кг, допускается интерьерное применение | [414 MDL, код 591](https://macons.md/vopsea-sansiro-7kg) | [ObraMag, 405 MDL, код 6000231](https://obramag.md/product/vopsea-universala-supraten-sansiro-7kg) | 401 MDL |

Указанные розничные цены — **снимок исследования**, а не гарантированные
текущие значения. Проверяйте ежемесячный результат сбора; в частности,
некоторые сайты могут блокировать автоматические запросы. Разные домены
магазинов ещё не доказывают независимость юридических лиц: это отдельная
проверка перед разрешением публикации.

## Как работает защита

1. В `price_sources.json` у всех шести товаров `tierCandidateForReview` —
   **только подсказка человеку**, а действительное `priceTier` остаётся `null`.
   Технически это разные продуктовые группы с общей ключевой позицией
   (`catalogMaterialKey`).
2. Скрипт `scripts/collect_prices.py` собирает живые наблюдения по каждому
   конкретному товару, сверяя заголовок, код и фасовку.
3. В `scripts/audit_prices.py` число **материалов** считается по уникальным
   ключам каталога; отдельный показатель сообщает число готовых к сравнению
   **товаров**. Нельзя считать три SKU тремя материалами.
4. `material_update_policy.json` сохраняет `enabled: false` и пустые
   `approvedMappings`; `prices.json` не меняется. Даже после просмотра
   результатов автоматическая публикация **не разрешается** сама собой.
5. Присвоение «Бюджет / Стандарт / Премиум» требует отдельной проверки
   характеристик и качества товаров, а не только их цен. При расхождениях
   магазинов, неработающих ссылках или неточных SKU товар блокируется.

Файлы этого пакета: `price_sources.json`, `scripts/audit_prices.py`,
`tests/test_verified_source_pack_alignment.py` и данный README. Ни Flutter
UI/расчёты, ни `prices.json` не включены.
