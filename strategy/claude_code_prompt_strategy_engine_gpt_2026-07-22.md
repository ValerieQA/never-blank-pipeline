# Prompt for Claude Code — Strategy Engine (GPT draft, 2026-07-22)

> Записано полностью, без правок, по просьбе Вали. Это альтернативный/более
> детальный вариант промпта для того же модуля, что описан в
> `strategy/claude_code_prompt_strategy_engine_2026-07-22.md`. Расхождения
> между двумя версиями см. в `decision_log.md`, Часть 8 — не отправлять
> Клоду Коду оба без согласования, какой именно (или какое объединение)
> использовать.

Ты работаешь в существующем production-репозитории Never Blank.
Твоя задача — не переписать систему с нуля и не создать ещё одну абстрактную архитектуру. Нужно изучить текущий код и встроить в существующий pipeline рабочий модуль стратегического планирования контента и продаж.

## Контекст продукта

Never Blank создавался не как генератор текстов.

Основная идея продукта:

Never Blank непрерывно анализирует рынок, определяет наиболее перспективную стратегию продаж и присутствия для малого бизнеса и реализует её через Compound Presence.

Compound Presence — это накопительный эффект постоянного присутствия бизнеса в релевантных точках контакта. Последовательные публикации, статьи, рыночные наблюдения и повторяющиеся смысловые сигналы со временем усиливают узнаваемость, доверие и вероятность обращения.

Контент является не самостоятельным продуктом, а способом реализации стратегии.

Never Blank также должен продавать сам себя. Его статьи и публикации демонстрируют качество анализа системы и помогают владельцу малого бизнеса узнать собственную проблему:

- присутствие зависит от свободного времени владельца;
- контент выходит нерегулярно;
- бизнес выпадает из поля зрения клиентов;
- рыночные возможности остаются незамеченными;
- публикации не связаны с общей продажной логикой;
- коммуникация не накапливает доверие.

Публикации не должны быть прямолинейной рекламой Never Blank. Они должны показывать проблему, механизм, коммерческое последствие и ценность Compound Presence так, чтобы читатель подумал:

«Да, это происходит у нас».

## Ключевая бизнес-логика

Система должна работать циклом:

```text
Market Research
→ Market Analysis
→ Sales Strategy
→ Monthly Content Strategy
→ Editorial Plan
→ Content Generation
→ Platform Adaptation
→ Distribution
→ Weekly Performance Review
→ Monthly Strategy Review
→ Continue / Adjust / Replace
```

Важно:

Стратегия не должна автоматически заменяться каждый месяц.

Если стратегия приводит к лидам, росту и сильным сигналам аудитории, она может продолжаться несколько месяцев.

Новый месяц не означает новую стратегию.

Новый месяц означает обязательную переоценку действующей стратегии.

## Главный критерий стратегии

Основной коммерческий KPI — лиды.

К лидам относятся:

- входящие сообщения;
- запросы на консультацию;
- запросы на демонстрацию;
- заполненные формы;
- email inquiries;
- LinkedIn DMs;
- сообщения в Instagram;
- Telegram inquiries;
- другие измеримые коммерческие обращения.

Дополнительные ранние сигналы:

- рост подписчиков;
- переходы на сайт;
- клики по CTA;
- сохранения;
- репосты;
- содержательные комментарии;
- охват;
- просмотры;
- рост engagement относительно предыдущего периода;
- публикации, значительно превысившие среднее значение;
- повторяющиеся реакции на одну и ту же проблему или тему.

Лайки сами по себе не являются доказательством успешной стратегии.

## Частота анализа

### Еженедельная проверка

В течение первого месяца новой стратегии review проводится каждую неделю.

Система должна определить одно из решений:

```text
CONTINUE
ADJUST_EXECUTION
REVIEW_STRATEGY
```

**CONTINUE** — используется, если: есть лиды; есть стабильный рост ранних показателей; несколько публикаций показывают положительную динамику; аудитория реагирует на ключевую проблему; текущая гипотеза получает подтверждение.

**ADJUST_EXECUTION** — используется, если сама стратегия выглядит перспективной, но требуется изменить: тему публикаций; hooks; CTA; платформенный формат; частоту; длину; visual approach; distribution timing; content mix. Изменение исполнения не должно автоматически считаться заменой стратегии.

**REVIEW_STRATEGY** — используется, если: лидов нет; нет роста ранних сигналов; публикации систематически ниже baseline; выбранная проблема не вызывает узнавания; CTA не вызывает действий; рыночная гипотеза не подтверждается; отрицательная динамика продолжается несколько недель.

### Месячная проверка

В конце каждого месяца система должна подготовить полный Strategy Review. Она должна ответить:

1. Какая стратегия действовала?
2. Почему она была выбрана?
3. Какие рыночные сигналы лежали в её основе?
4. Какая основная проблема малого бизнеса использовалась?
5. Какой продажный механизм применялся?
6. Какие темы публиковались?
7. Какие hooks сработали лучше?
8. Какие Echo сработали лучше?
9. Какие CTA дали действия?
10. Какие платформы дали лучшие результаты?
11. Сколько было лидов?
12. Какие публикации стали outliers?
13. Есть ли положительная тенденция?
14. Подтверждена ли стратегия?
15. Нужно ли продолжить, скорректировать или заменить её?

Возможные решения:

```text
CONTINUE_STRATEGY
CONTINUE_WITH_ADJUSTMENTS
REPLACE_STRATEGY
INSUFFICIENT_DATA
```

## Research и Market Analysis

Перед созданием стратегии система должна анализировать рынок малого бизнеса. Исследование должно учитывать: изменения поведения владельцев малого бизнеса; проблемы с постоянным онлайн-присутствием; изменения покупательского поведения; экономические сигналы; новые маркетинговые практики; продажи; доверие; brand visibility; social proof; demand generation; LinkedIn; Instagram; Facebook; Threads; Telegram; SEO; GEO; AI search; platform algorithms; content saturation; конкурентную среду; технологические изменения; новые риски и возможности для малого бизнеса.

Research не должен быть простым списком новостей. Каждый сигнал должен содержать:

```json
{
  "signal": "",
  "source": "",
  "source_date": "",
  "market_area": "",
  "affected_audience": "",
  "change_detected": "",
  "why_it_matters": "",
  "business_implication": "",
  "sales_implication": "",
  "compound_presence_implication": "",
  "confidence": "high | medium | low",
  "freshness": "",
  "evidence": []
}
```

Система должна отделять: отдельную новость; временный шум; повторяющийся паттерн; значимый рыночный сдвиг; actionable opportunity.

## Pattern Extractor

Pattern Extractor требуется зафиксировать как отдельный слой, к которому архитектурно нужно вернуться. Если полноценная реализация сейчас слишком рискованна для production pipeline, создай минимальную рабочую версию без переусложнения.

Его задача — превращать market signals в стратегически полезные паттерны. Пример структуры:

```json
{
  "pattern_id": "",
  "pattern_name": "",
  "observed_signals": [],
  "small_business_situation": "",
  "underlying_mechanism": "",
  "customer_behavior": "",
  "business_risk": "",
  "business_opportunity": "",
  "sales_relevance": "",
  "content_relevance": "",
  "compound_presence_relevance": "",
  "confidence": "high | medium | low"
}
```

## Monthly Sales Strategy

На основе исследования система должна сформировать не просто content theme, а продажную стратегию. Стратегия должна быть сформулирована человеческим языком. Пример:

```json
{
  "strategy_id": "2026-08-trust-compound-presence",
  "status": "active",
  "started_at": "2026-08-01",
  "review_date": "2026-08-31",
  "strategy_name": "Build demand through recognition of inconsistent presence",
  "strategy_summary": "",
  "market_context": "",
  "selected_problem": "",
  "target_audience": "small business owners",
  "sales_hypothesis": "",
  "why_now": "",
  "commercial_goal": "",
  "primary_message": "",
  "supporting_messages": [],
  "compound_presence_role": "",
  "desired_reader_realization": "",
  "primary_cta_intent": "",
  "success_criteria": {},
  "continuation_criteria": {},
  "adjustment_criteria": {},
  "replacement_criteria": {},
  "research_references": [],
  "confidence": "high | medium | low"
}
```

## Monthly Content Plan

Система должна автоматически создавать контент-план примерно на три основные публикации в неделю. Ориентир: 12–14 основных тем в месяц; дополнительные короткие platform-native публикации; статьи для сайта; самостоятельные версии для соцсетей.

Каждая тема должна быть напрямую связана со стратегией. Для каждой темы сохранять:

```json
{
  "content_id": "",
  "week": 1,
  "publication_date": "",
  "strategy_id": "",
  "content_role": "recognition | education | proof | reframe | objection | conversion",
  "topic": "",
  "working_title": "",
  "target_reader": "",
  "reader_problem": "",
  "market_signal": "",
  "pattern": "",
  "sales_objective": "",
  "main_argument": "",
  "hook": "",
  "recognition": "",
  "mechanism": "",
  "business_consequence": "",
  "reframe": "",
  "compound_presence_connection": "",
  "echo": "",
  "cta_intent": "",
  "cta": "",
  "website_angle": "",
  "linkedin_angle": "",
  "instagram_angle": "",
  "facebook_angle": "",
  "threads_angle": "",
  "telegram_angle": "",
  "seo_keywords": [],
  "geo_questions": [],
  "internal_links": [],
  "status": "planned"
}
```

Echo обязателен. Если Echo отсутствует, материал не должен считаться готовым.

## Editorial Strategy

Статья должна продавать Never Blank через демонстрацию мышления, а не через прямую рекламу.

Обязательная логика статьи:

```text
Hook
→ Recognition
→ Tension
→ Market Observation
→ Investigation
→ Mechanism
→ Business Consequence
→ Reframe
→ Compound Presence Connection
→ Echo
→ Soft CTA
```

### Требования к статье

Статья должна: начинаться с узнаваемой ситуации владельца малого бизнеса; не начинаться с корпоративной новости; использовать компанию, тренд или новость как доказательство механизма; показывать коммерческое последствие; переосмысливать очевидное объяснение; связывать проблему с постоянным присутствием; демонстрировать качество анализа Never Blank; содержать обязательный Echo; не превращаться в прямой рекламный pitch; вести к мягкому коммерческому действию.

Пример желаемого эффекта: «У нас действительно присутствие зависит от того, успеваю ли я что-то публиковать».

Echo должен быть смыслом, который остаётся после текста. Пример: «Клиенты редко принимают решение забыть компанию. Они просто перестают её регулярно встречать». Не копируй этот Echo во все статьи. Генерируй уникальный Echo, заработанный содержанием конкретной статьи.

## Platform Strategy

Не допускается создание одного текста с последующим механическим сокращением. Каждая платформа должна получать самостоятельную композицию.

**Website** — учитывать: SEO; GEO; поисковый интент; query coverage; понятную структуру; подзаголовки; внутренние ссылки; фактические источники; краткий ответ на вопрос пользователя; semantic completeness; AI-search readability.

**LinkedIn** — учитывать: B2B-аудиторию; профессиональное узнавание; сильный opening; dwell time; сохранения; комментарии; разговорность; отсутствие перегруженности; актуальные платформенные рекомендации, если они доступны в research layer.

**Instagram** — учитывать: visual hook; carousel logic или другой подходящий формат; save/share intent; ясную композицию; отдельный caption; отсутствие простого копирования LinkedIn.

**Facebook** — создавать самостоятельный разговорный пост. Не использовать LinkedIn-текст повторно.

**Threads** — использовать структуру: `Hook → Recognition → Mechanism → Reframe → Echo`. Обычно 3–5 самостоятельных posts. Не использовать бессмысленные hashtags.

**Telegram** — короткий самостоятельный сигнал: `Observation → Business Implication → Optional Link`. Не публиковать полный текст статьи.

## Analytics Model

Создай нормализованную модель метрик. Пример:

```json
{
  "content_id": "",
  "platform": "",
  "published_at": "",
  "impressions": 0,
  "reach": 0,
  "views": 0,
  "likes": 0,
  "comments": 0,
  "shares": 0,
  "saves": 0,
  "profile_visits": 0,
  "new_followers": 0,
  "link_clicks": 0,
  "website_sessions": 0,
  "cta_actions": 0,
  "leads": 0,
  "qualified_leads": 0,
  "notes": ""
}
```

Система должна уметь работать даже при неполных данных. Не все платформы предоставляют одинаковые метрики. Не подставляй нули, если данные отсутствуют. Отличай: `0` — подтверждённое отсутствие; `null` — данные недоступны; `not_collected` — данные пока не собраны.

## Strategy History

История стратегий обязательна. Нельзя перезаписывать предыдущую стратегию. Для каждой стратегии сохранять: первоначальную версию; обоснование; research snapshot; изменения; weekly reviews; monthly review; итоговые метрики; решение; lessons learned.

Пример структуры:

```text
strategy/
  current/
    strategy.json
    strategy.md
    content_plan.json
    content_plan.csv
    content_plan.md

  history/
    2026-08-trust-compound-presence/
      strategy.json
      strategy.md
      research_snapshot.json
      content_plan.json
      content_plan.csv
      weekly_review_01.json
      weekly_review_01.md
      weekly_review_02.json
      weekly_review_02.md
      monthly_review.json
      monthly_review.md
      lessons.json

  methodology/
    strategy_methodology.md
    evaluation_rules.md
    editorial_strategy.md
    platform_strategy.md
```

Можно адаптировать структуру под существующий репозиторий, но история должна быть: человекочитаемой; машиночитаемой; version-controlled; пригодной для аудита.

## Human-readable output

Каждый важный JSON должен иметь эквивалент в Markdown. Пользователь должен иметь возможность открыть GitHub и без чтения кода понять: какая стратегия сейчас действует; почему она выбрана; какие темы запланированы; какие hooks используются; где Echo; что продаёт каждая статья; какие результаты получены; почему стратегия продолжена или изменена.

Также создай CSV, который можно открыть в Excel или Google Sheets. В CSV контент-плана должны быть колонки:

```text
Date
Week
Strategy
Content Role
Topic
Title
Target Reader
Reader Problem
Market Signal
Sales Objective
Hook
Recognition
Mechanism
Business Consequence
Reframe
Compound Presence Connection
Echo
CTA Intent
CTA
Website Angle
LinkedIn Angle
Instagram Angle
Facebook Angle
Threads Angle
Telegram Angle
SEO Keywords
GEO Questions
Status
```

## Integration Requirements

Сначала изучи репозиторий. Найди: текущие research workflows; editorial engine; content package generation; publishing pipeline; reporting; GitHub Actions; конфигурацию; существующие документы; decision log; tests.

Не создавай дублирующую параллельную систему, если можно расширить существующую. Не ломай текущий production flow.

Перед внесением изменений подготовь краткий implementation plan с указанием: 1. существующих файлов, которые будут изменены; 2. новых файлов; 3. migration path; 4. рисков; 5. тестов; 6. способов отката.

После этого реализуй изменения.

## MVP Boundary

Не нужно строить идеальную автономную систему любой ценой. Первая версия должна реально работать. Раздели реализацию на этапы.

**Phase 1 — Strategy artifacts** — модели данных; генерация strategy.json; генерация strategy.md; генерация content plan; CSV для Excel; история стратегий; ручной или fixture-based ввод метрик; weekly/monthly review logic.

**Phase 2 — Research integration** — использование существующего Research Engine; преобразование сигналов в strategy inputs; минимальный Pattern Extractor; traceability от темы статьи к исходным сигналам.

**Phase 3 — Editorial integration** — передача strategy context в Editorial Engine; обязательные hook, mechanism, reframe, Echo, CTA; validation gates; platform-specific rendering.

**Phase 4 — Performance integration** — автоматическое получение доступных метрик; lead tracking adapters; weekly review automation; monthly review automation; recommendation: continue / adjust / replace.

Не реализуй Phase 4 фиктивно, если необходимые API и данные отсутствуют. Создай интерфейсы и честно отметь unavailable integrations.

## Validation Rules

Добавь проверки.

Стратегия считается невалидной, если отсутствуют: market context; selected problem; sales hypothesis; commercial goal; compound presence role; success criteria; research references.

Контент-план считается невалидным, если: меньше требуемого числа тем; темы не связаны со strategy_id; нет sales objective; нет hook; нет mechanism; нет reframe; нет Echo; нет CTA intent; нет платформенных углов; несколько публикаций чрезмерно дублируют друг друга.

Статья считается невалидной, если: начинается как пересказ новости; компания является главным героем вместо владельца малого бизнеса; отсутствует коммерческое последствие; отсутствует Compound Presence connection; отсутствует Echo; CTA не соответствует стратегии; текст содержит неподтверждённые факты; разные платформы получают почти одинаковый текст.

Используй fail-closed поведение перед публикацией критически невалидного материала.

## Decision Log

Обнови существующий `decision_log` или аналогичный документ. Зафиксируй:

**Product principle.** Never Blank изначально создавался как система, которая непрерывно анализирует рынок, определяет наиболее перспективную стратегию для малого бизнеса и реализует её через Compound Presence. Это не новое позиционирование.

**Current implementation decision.** Автоматизированный Strategy Engine внедряется поэтапно и не должен блокировать стабильную работу существующего production pipeline.

**Strategy continuation rule.** Месячный review не означает обязательную замену стратегии. Рабочая стратегия продолжается, пока создаёт лиды или подтверждённую положительную динамику.

**Primary KPI.** Главный критерий — лиды. Engagement metrics являются вспомогательными и диагностическими.

**Pattern Extractor.** Pattern Extractor признан необходимым архитектурным слоем. К его полноценной реализации необходимо вернуться после стабилизации основной интеграции. В MVP допускается минимальная версия.

**Content principle.** Контент — реализация стратегии и демонстрация мышления Never Blank, а не самостоятельный продукт.

**Platform principle.** Каждая платформа получает самостоятельную композицию, а не сокращённую копию одной статьи.

## Tests

Добавь unit tests и integration tests минимум для: strategy schema validation; strategy continuation decision; adjustment decision; replacement decision; insufficient data decision; content plan validation; Echo requirement; traceability to research; CSV export; Markdown rendering; history preservation; prevention of strategy overwrite; platform duplication detection; fail-closed publishing gate.

Добавь fixtures минимум для трёх сценариев: 1. Стратегия привела к лидам — продолжить. 2. Лидов пока нет, но есть устойчивый рост ранних сигналов — продолжить с корректировками или собрать больше данных. 3. Нет лидов и нет положительной динамики — заменить стратегию.

## Final deliverables

После реализации предоставь: 1. Краткое описание найденной текущей архитектуры. 2. Список изменённых файлов. 3. Список новых файлов. 4. Объяснение новой логики. 5. Пример сгенерированной Monthly Strategy. 6. Пример content plan. 7. Пример CSV. 8. Пример weekly review. 9. Пример monthly review. 10. Результаты тестов. 11. Известные ограничения. 12. Что осталось для следующих фаз. 13. Точный список GitHub Actions, которые были изменены или добавлены. 14. Подтверждение, что существующий production pipeline не был сломан.

Не утверждай, что интеграция работает, если она не была протестирована. Не скрывай ошибки. Не создавай фиктивные метрики, лиды или источники.

Сначала проанализируй репозиторий, затем покажи implementation plan, после чего приступай к изменениям.
