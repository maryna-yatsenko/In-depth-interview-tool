# План правок — admin-visual-hierarchy (dry-run, без live-скріншотів)

Скоуп: `web/admin.html`, `web/admin.css`. `web/styles.css` — лише читання
(токени `--bg/--surface/--text/--muted/--line/--danger/--good/--warn/--radius/--shadow-sm`
і shared-класи `.primary`/`.ghost`/`.actions` лишаються без змін).

Примітка щодо стану кодової бази: цей worktree вже пройшов рефакторинг
(TTS-провайдери, `guard.py` та частина карток тем видалені; теми тепер —
один `textarea#guide-topics`, а не список карток із `.topic-title-input`).
Тому кілька прикладів у `hierarchy-patterns.md` (картки тем, "Змінити
порядок" поруч зі "Зберегти" в `#tab-guide`) у поточному HTML вже не
існують — відповідні пункти нижче позначені як "вже відповідає / нема
цілі", а не пропущені.

## 1. Фіолетові токени в `body.admin` (color-tokens.md, "Де міняти")

Селектор: новий блок на початку `admin.css`, одразу після `body.admin { background: var(--bg); }`.

Before: токенів `--accent-soft/--accent-tint/--accent-strong` нема взагалі;
`--accent`/`--heading` беруться з синього `:root` у `styles.css`.

After (дослівно з `color-tokens.md`, без змін):
```css
body.admin {
  --accent: #8b71ee;
  --accent-soft: #c7b8f9;
  --accent-tint: #f5f0ff;
  --accent-strong: #5a33b5;
  --heading: #5a33b5;
  --on-accent: #fff;
}
@media (prefers-color-scheme: dark) {
  body.admin {
    --accent: #8b71ee;
    --accent-soft: #5a33b5;
    --accent-tint: #3d2f66;
    --accent-strong: #c7b8f9;
    --heading: #c7b8f9;
    --on-accent: #141414;
  }
}
```
Обґрунтування: `color-tokens.md`, розділ "Де міняти" — точний код, `:root`
у `styles.css` не чіпаємо, синій там лишається для сторінки респондента.
Наслідок каскаду: `.section-head h2` (вже `color: var(--heading)`) і
`.tab.active`/фокус-рамки/бордери (вже `var(--accent)`) автоматично
стають фіолетовими без додаткових правок у цих селекторах.

## 2. `.primary` (заливка кнопки) — текстовий контраст

Селектор: новий `body.admin .primary` в `admin.css` (сам `.primary` лишається
в `styles.css` незмінним — редагуємо лише через специфічність в admin.css).

Before: `.primary { background: var(--accent); color: var(--on-accent); }`
(успадковано) → тло `#8b71ee`, контраст з білим текстом 3.69:1 — не
проходить 4.5:1 для звичайного тексту кнопки.

After:
```css
body.admin .primary { background: var(--accent-strong); }
```
→ тло `#5a33b5` (світла тема) / `#c7b8f9` (темна, разом із вже коректним
`--on-accent` темним текстом) — 8.16:1 / 10.5:1.

Обґрунтування: `color-tokens.md` — "там, де ... використовується `--accent`
для тексту або тла кнопки з білим текстом — підставляти `#5A33B5`".

## 3. `.turn.interviewer .who` — текстове використання `--accent`

Селектор: `.turn.interviewer .who` в `admin.css`.

Before: `color: var(--accent);` (12px, не bold, не ≥18px → потрібно 4.5:1,
є лише 3.69:1).

After: `color: var(--accent-strong);`

Обґрунтування: та сама практична настанова з `color-tokens.md` — це єдине
інше місце в `admin.css`, де `--accent` стоїть на тексті, а не на
бордері/фокус-кільці/decorative-штриху (ті лишаються `--accent` — поріг
для них 3:1, `#8b71ee` проходить).

## 4. `.new-space` — тло-натяк замість нейтральної картки

Селектор: `.new-space` в `admin.css`.

Before: `background: var(--surface); border: 1px solid var(--accent); ...`

After: `background: var(--accent-tint); border: 1px solid var(--accent);`
(бордер лишається — тепер тло + бордер разом читаються як акцентний
колаут, а не звичайна картка).

Обґрунтування: `hierarchy-patterns.md`, патерн 3 — `.new-space` названо
прямим кандидатом на кольоровий тінт замість `--surface`.

## 5. `.run .pill` / `.pill.warn` — заповнене тло замість тільки бордера

Селектор: `.run .pill`, `.run .pill.warn` в `admin.css`.

Before:
```css
.run .pill { font-size: 12px; padding: 3px 8px; border-radius: 20px; border: 1px solid var(--line); color: var(--muted); }
.run .pill.warn { color: var(--danger); border-color: var(--danger); }
```

After:
```css
.run .pill { font-size: 12px; padding: 3px 8px; border-radius: 20px; border: none; background: var(--accent-soft); color: var(--accent-strong); font-weight: 500; }
.run .pill.warn { background: var(--danger); color: var(--on-danger); }
```

Обґрунтування:
- Нейтральна пігулка (кількість реплік) — `color-tokens.md`, роль
  `--accent-soft`: "тло бейджа/тега ... з `--text` чи `--accent-strong`
  поверх, не з білим" — саме та пара токенів, без вигаданих значень.
- `.pill.warn` (інциденти) — це вже семантичний статус-стан (проблема), не
  фіолетова шкала, тому `hierarchy-patterns.md` патерн 4 прямо каже не
  чіпати акцентну шкалу для статусів і брати вже наявні перевірені
  токени: `--danger`/`--on-danger` вже існують і вже WCAG-перевірені в
  `styles.css`, тому суцільна заливка `--danger` + `--on-danger` — це той
  самий "суцільне кольорове тло пігулки" приклад із HR-дашборду в патерні
  4, без жодного нового кольору.

**Явно не зроблено (застережний пункт, а не мовчазний пропуск):**
`.delete-confirm`/`.purge-confirm` (картки підтвердження видалення) за
патерном 3 теж кандидати на кольоровий тінт (зараз — просто
`background: var(--surface)` + `border: 1px solid var(--danger)`), але
жоден з двох reference-файлів не дає точного hex для "приглушеного
danger-тону" (є лише для фіолетової шкали). Вигадувати цей відтінок —
порушення прямої вказівки "не вигадуй кольори заново", тому картки
підтвердження лишені як є; це рішення для окремого проходу, коли
з'явиться точний danger-tint токен.

## 6. Групування полів на вкладці "Налаштування" (`#tab-space`) — fieldset/legend

Явно дозволений виняток зі скоупу (SKILL.md, розділ "Що не входить...",
пункт про `<fieldset class="field-group">`+`<legend>`): обгортка наявних
полів без зміни розмітки лейбл↔поле, нових полів, нової функціональності.

`#tab-space` зараз — суцільний потік із 13 полів/чекбоксів без жодного
візуального розмежування (на відміну від `#tab-guide`, де вже є
`.section-head` "Теми"). Групи складені без зміни порядку елементів у DOM
(лише обгортка суміжних, уже існуючих полів):

1. **«Дослідження»** — Назва, Мови (`.row`), Звертання, Тон (`.row`),
   Як інтервʼюер представляється.
2. **«Лексика та межі»** — Лексика домену (+ підказка), Ніколи не питати
   про.
3. **«Приватність»** — чекбокс «Вичищати персональні дані», Шаблони
   маскування (+ підказка).
4. **«Респондент»** — чекбокс «Готовий до інтервʼю», Текст згоди,
   Розділи звіту.
5. **«Інтерфейс»** — чекбокс «Озвучувати автоматично», Режим інтерфейсу,
   Акцентний колір / Заголовок сторінки (`.row`).

`.actions.sticky` (кнопка «Зберегти») і секція «Видалення» лишаються поза
fieldset-ами: перше — спільний action-bar для всієї вкладки, друге вже
має власний `.section-head` (окремий, уже правильний патерн 5) і за
змістом — це вже деструктивна дія, а не кластер звичайних полів форми.

Обґрунтування: `hierarchy-patterns.md`, патерн 3, абзац "Механізм для
звичайних полів форми" — прямо називає `#tab-space` як кандидата, з
природним поділом типу "параметри" від "змістовних" полів; тут поділ
деталізований під реальний (інший, ніж в описі скіла) набір полів
поточного `admin.html`.

CSS для нового `fieldset.field-group`/`legend` (`admin.css`) — свідомо
БЕЗ кольорового тла (fieldset — це не колаут, `hierarchy-patterns.md` явно
розрізняє "механізм для звичайних полів форми (не колаутів)" і кольоровий
тінт для карток-колаутів із п.4 вище). Legend стилізовано як мітка з
патерну 1 (uppercase, приглушена, дрібна) — узгоджено з існуючим
`.section-head`:

```css
fieldset.field-group {
  border: none; margin: 0 0 22px; padding: 0; min-width: 0;
}
fieldset.field-group legend {
  padding: 0; margin: 0 0 10px;
  font-size: 12px; font-weight: 600; letter-spacing: .04em;
  text-transform: uppercase; color: var(--muted);
}
fieldset.field-group > label:last-child,
fieldset.field-group > .row:last-child { margin-bottom: 0; }
```

## Патерни без правок (уже відповідають референсу — перевірено, не мовчазний пропуск)

- **Патерн 1 (мітка+значення):** конкретні цілі з `hierarchy-patterns.md`
  (`.topic-title-input`) у поточному HTML вже не існують (теми — плоский
  `textarea`, не картки). `.space-list button` вже успадковує `--text`
  (не `--muted`) для назви простору — уже відповідає.
- **Патерн 2 (один primary):** `#tab-guide` і `#tab-space` мають рівно по
  одній `.primary` в `.actions.sticky`; конфлікт "Зберегти" +
  "Змінити порядок" з опису скіла в поточному коді відсутній (немає такої
  другої кнопки).
- **Патерн 5 (дистанція секцій):** `.section-head { margin: 26px 0 6px; }`
  — уже правильна асиметрія, не чіпаємо.
- **Патерн 6 (рядок списку):** `.space-list button` / `.sub` уже мають
  потрібну пару вага/приглушеність.

## Підсумок файлових правок

- `web/admin.css`: пункти 1–6 (токени, `.primary`, `.turn.interviewer .who`,
  `.new-space`, `.run .pill`/`.pill.warn`, `fieldset.field-group`).
- `web/admin.html`: лише `#tab-space` — обгортка існуючих полів у 5
  `<fieldset class="field-group"><legend>…</legend>…</fieldset>`, без
  зміни ids/name/placeholder/порядку елементів.
- `web/styles.css`, `web/index.html`, `web/app.js`, `web/admin.js` —
  без змін (поза скоупом).
