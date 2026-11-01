# COSTARO: восстановление четырёх источников материалов

Исправление по фактическому журналу `COSTARO Monthly Market Check #4`
(01.11.2026). В журнале из 54 запросов 50 дали цену; два запроса Domic
получили `ambiguous`, два запроса Teremok — `unavailable`.

## Что исправлено

| Материал | Ошибка | Действие |
|---|---|---|
| Шпаклёвка Meșterul Manole, 8 кг | Domic `ambiguous` | Читать из JSON-LD точный `mpn=240`, `sku=91`, цену 167 MDL. |
| Краска ROMANIȚA, 7 кг | Domic `ambiguous` | Читать из JSON-LD точный `mpn=285`, `sku=136`, цену 214 MDL. |
| Грунтовка Supraton Extra, 15 кг | Teremok `unavailable` | Заменить Teremok на [DocConstruct, код dc100](https://docconstruct.md/ro/grund-supraton-extra-15kg/100). |
| Клей Class Nas, 25 кг | Teremok `unavailable` | Заменить Teremok на [ObraMag, код 510014](https://obramag.md/product/adeziv-gresiefaianta-class-nas-gri-25kg). |

Подтверждённая фасовка грунтовки — 15 кг, клея — 25 кг. На сайтах
DocConstruct и ObraMag были опубликованы цены 565 и 111 MDL соответственно.
Это примеры на дату исследования, а не цена для публикации в каталоге.

## Почему Domic теперь должен распознаваться

Сайты Macons/ObraMag предоставляют цену и артикул в микроданных.
У Domic реальный код товара находится в JSON-LD `mpn`, а `sku` —
внутренний идентификатор страницы. Раньше сборщик сравнивал только `sku`
с кодом магазина, отклонял правильный товар и попадал на неоднозначные
видимые цены. Теперь допускается точное совпадение **SKU или MPN**,
но по-прежнему нужно совпадение названия и ровно одной цены.
Для DocConstruct принимается `priceCurrency: "mdl"` как валюта MDL.

Для плиточного клея заданы общие термины `Class Nas` и `25kg`:
они совпадают в названиях разных магазинов, даже если перед ними
встречается текст «pentru gresie/faianta», а после — слово «gri».

**Важно:** JSON-LD по-прежнему отмечается методом `structured_data`,
а не повышается искусственно до строго проверенной микроподписи
`product_microdata`. Поэтому этот пакет не открывает путь к автоматической
публикации цены по неполным доказательствам. У DocConstruct также нужно
отдельно проверить актуальность предложения перед будущим одобрением цены.

## Защита

- `prices.json`, `app_embedded_baseline.json`, приложение Flutter и нормы
  расхода **не изменялись**.
- `price_sources.json` сохраняет `automaticPublicationEnabled: false`.
- `material_update_policy.json` сохраняет `enabled: false` и пустые
  `approvedMappings`.
- После установки нужно запустить **COSTARO Monthly Market Check** и
  проверить фактические статусы четырёх источников. Зелёный статус GitHub
  сам по себе не означает, что каждая ссылка вернула достоверную цену.

В архиве только четыре файла: `price_sources.json`,
`scripts/collect_prices.py`, `tests/test_recover_four_price_sources.py`
и данный README.
