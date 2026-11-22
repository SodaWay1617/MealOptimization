import React, { useState } from 'react';
import { ingredientKey, readPreference, shops, writePreference } from './shoppingPreferences.js';

export function ShoppingPreferences({ recipes }) {
  const [store, setStore] = useState(() => readPreference('shopping-context', {}).store ?? 'lenta');
  const [rules, setRules] = useState(() => readPreference('shopping-rules', ''));
  const [links, setLinks] = useState(() => readPreference('shopping-links', {}));
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState('');
  const counts = new Map();
  for (const recipe of recipes) {
    for (const name of new Set(recipe.ingredients.map((item) => ingredientKey(item.name)))) {
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
  }
  for (const name of Object.keys(links[store] ?? {})) {
    if (!counts.has(name)) counts.set(name, 0);
  }
  const ingredients = [...counts].sort(([a, left], [b, right]) => right - left || a.localeCompare(b, 'ru'));

  function changeLink(index, value) {
    const ordered = [...(links[store]?.[selected] ?? ['', '', ''])];
    ordered[index] = value;
    const next = { ...links, [store]: { ...links[store], [selected]: ordered } };
    setLinks(next);
    writePreference('shopping-links', next);
  }

  return <section className="panel plan-controls">
    <h1>Предпочтения</h1>
    <label>Постоянные правила для AI
      <textarea rows={5} maxLength={4000} value={rules} placeholder="Например, молоко 2,5%, ржаной хлеб без добавок."
        onChange={(event) => { setRules(event.target.value); writePreference('shopping-rules', event.target.value); }} />
    </label>
    <fieldset>
      <legend>Приоритетные товары</legend>
      <p>Укажите до трёх ссылок в порядке предпочтения. Список ингредиентов отсортирован по числу рецептов.</p>
      <div className="plan-fields">
        <label>Магазин<select value={store} onChange={(event) => { setStore(event.target.value); setSelected(''); }}>
          {shops.map((shop) => <option key={shop.id} value={shop.id}>{shop.name}</option>)}
        </select></label>
        <label>Поиск ингредиента<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <label>Ингредиент<select value={selected} onChange={(event) => setSelected(event.target.value)}>
          <option value="">Выберите ингредиент</option>
          {ingredients.filter(([name]) => name === selected || name.includes(ingredientKey(query))).map(([name, count]) => (
            <option key={name} value={name}>{name} · {count}{links[store]?.[name]?.some(Boolean) ? ' ★' : ''}</option>
          ))}
        </select></label>
      </div>
      {selected && [0, 1, 2].map((index) => <label key={index}>Приоритет {index + 1}
        <input type="url" maxLength={1500} value={links[store]?.[selected]?.[index] ?? ''}
          onChange={(event) => changeLink(index, event.target.value)} placeholder="Ссылка на товар в магазине" />
      </label>)}
      <small>Изменения сохраняются в этом браузере.</small>
    </fieldset>
  </section>;
}
