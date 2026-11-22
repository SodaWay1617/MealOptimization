import React, { useEffect, useRef, useState } from 'react';
import { StoreCart } from './StoreCart.jsx';
import { PlanArchive } from './PlanArchive.jsx';

function localDate(offset = 0) {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return [date.getFullYear(), date.getMonth() + 1, date.getDate()]
    .map((value) => String(value).padStart(2, '0')).join('-');
}

const newSlot = (category) => ({ id: crypto.randomUUID(), category, tag: '', count: 1, days: 1 });

export function MealPlan({ active, categories, tags, recipes, request, send, sendStore, onOpenRecipe }) {
  const [start, setStart] = useState(() => localDate());
  const [end, setEnd] = useState(() => localDate(6));
  const [people, setPeople] = useState(1);
  const [slots, setSlots] = useState(() => ['breakfast', 'soup', 'main', 'salad', 'snack', 'drink']
    .filter((category) => categories[category]).map(newSlot));
  const [prompt, setPrompt] = useState('');
  const [useSlots, setUseSlots] = useState(false);
  const [pantry, setPantry] = useState('');
  const [plan, setPlan] = useState(null);
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState('');
  const [showForm, setShowForm] = useState(false);
  const formSection = useRef(null);
  useEffect(() => {
    if (showForm) formSection.current?.scrollIntoView({ block: 'start' });
  }, [showForm]);
  const days = Math.max(1, Math.round((Date.parse(end) - Date.parse(start)) / 86400000) + 1 || 1);

  function changeSlot(id, change) {
    setSlots((current) => current.map((slot) => slot.id === id ? { ...slot, ...change } : slot));
  }

  function changeEntry(id, change) {
    setPlan({ ...plan, entries: plan.entries.map((entry) => entry.id === id ? { ...entry, ...change } : entry) });
    setDirty(true);
    setSaved('');
  }

  async function generate(mode) {
    setPending(mode);
    setError('');
    setSaved('');
    try {
      const result = await send({
        mode, start, end, people, slots: mode === 'ai' && !useSlots ? [] : slots,
        prompt, pantry: pantry.split(/[,\n]/).map((item) => item.trim()).filter(Boolean),
        entries: plan?.entries ?? [],
      });
      setPlan({ ...result, notices: mode === 'preview' || mode === 'save' ? plan?.notices ?? [] : result.notices });
      setStart(result.start);
      setEnd(result.end);
      setPantry(result.pantry.join(', '));
      setDirty(false);
      setSaved(result.filename ?? '');
    } catch (failure) {
      setError(failure.message);
    } finally {
      setPending('');
    }
  }

  return (
    <div className="meal-planner">
      <PlanArchive active={active} request={request} saved={saved} recipes={recipes}
        onOpenRecipe={onOpenRecipe} onCreate={() => setShowForm(true)} />
      {showForm && <section className="panel plan-controls" ref={formSection}>
        <div className="plan-archive-heading"><h2>Новый план</h2><button onClick={() => setShowForm(false)}>Свернуть</button></div>
        <fieldset disabled={!!pending}>
          <legend>Период и порции · {days} дн.</legend>
          <div className="plan-fields">
            <label>С<input type="date" value={start} onChange={(event) => { setStart(event.target.value); setDirty(true); setSaved(''); }} /></label>
            <label>По<input type="date" min={start} value={end} onChange={(event) => { setEnd(event.target.value); setDirty(true); setSaved(''); }} /></label>
            <label>Едоков по умолчанию<input type="number" min="1" max="50" value={people} onChange={(event) => setPeople(Number(event.target.value))} /></label>
          </div>
        </fieldset>
        <fieldset disabled={!!pending}>
          <legend>Случайный подбор</legend>
          {slots.map((slot) => (
            <div className="plan-fields plan-slot" key={slot.id}>
              <label>Категория<select value={slot.category} onChange={(event) => changeSlot(slot.id, { category: event.target.value })}>
                {Object.entries(categories).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
              </select></label>
              <label>Условие<select value={slot.tag} onChange={(event) => changeSlot(slot.id, { tag: event.target.value })}>
                <option value="">Любое</option><option value="regular">Обычное</option>
                {Object.entries(tags).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
              </select></label>
              <label>Разных блюд<input type="number" min="1" max="20" value={slot.count} onChange={(event) => changeSlot(slot.id, { count: Number(event.target.value) })} /></label>
              <label>Дней на блюдо<input type="number" min="1" max={days} value={slot.days} onChange={(event) => changeSlot(slot.id, { days: Number(event.target.value) })} /></label>
              <button type="button" aria-label="Удалить условие" onClick={() => setSlots(slots.filter(({ id }) => id !== slot.id))}>×</button>
            </div>
          ))}
          <div className="plan-actions">
            <button type="button" onClick={() => setSlots([...slots, newSlot(Object.keys(categories)[0])])}>Добавить условие</button>
            <button type="button" onClick={() => generate('random')}>Собрать случайно</button>
          </div>
        </fieldset>
        <fieldset disabled={!!pending}>
          <legend>Подбор с AI</legend>
          <label>Какое меню собрать<textarea rows={3} maxLength={4000} value={prompt} onChange={(event) => setPrompt(event.target.value)}
            placeholder="Три дня на двоих. Некогда готовить, на куриную лапшу всё есть…" /></label>
          <label className="plan-check"><input type="checkbox" checked={useSlots} onChange={(event) => setUseSlots(event.target.checked)} /> Учесть условия подбора выше</label>
          <small>Запрос и данные о доступных рецептах передаются в OpenRouter.</small>
          <div className="plan-actions"><button className="primary" disabled={!prompt.trim()} onClick={() => generate('ai')}>Собрать с AI</button></div>
        </fieldset>
        <label>Продукты дома<textarea rows={2} value={pantry} onChange={(event) => { setPantry(event.target.value); setDirty(true); setSaved(''); }} placeholder="Названия через запятую или с новой строки" /></label>
      </section>}
      {pending && <p role="status">{pending === 'ai' ? 'AI подбирает блюда…' : 'Обновляем план…'}</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {plan && <section className="panel plan-result">
        <h2>Меню · {plan.start} — {plan.end}</h2>
        {plan.notices.map((notice, index) => <p key={index}>{notice}</p>)}
        {plan.entries.length === 0 && <p>Подходящие блюда не найдены.</p>}
        {plan.entries.map((entry) => (
          <div className="plan-fields plan-dish" key={entry.id}>
            <button type="button" onClick={() => onOpenRecipe(entry.id)}>{entry.title}</button>
            <label>Дней<input type="number" min="1" max={days} value={entry.days} onChange={(event) => changeEntry(entry.id, { days: Number(event.target.value) })} /></label>
            <label>Едоков<input type="number" min="1" max="50" value={entry.people} onChange={(event) => changeEntry(entry.id, { people: Number(event.target.value) })} /></label>
            <span>{entry.days * entry.people} порц.</span>
            {!dirty && entry.costRub != null && <span>≈ {entry.costRub.toLocaleString('ru-RU')} ₽{entry.portionPrice.missing.length ? ' · частично' : ''}</span>}
            <label className="stocked"><input type="checkbox" checked={entry.stocked} onChange={(event) => changeEntry(entry.id, { stocked: event.target.checked })} /> Всё есть дома</label>
          </div>
        ))}
        {!dirty && plan.costRub != null && <p><strong>Оценка стоимости меню</strong> ≈ {plan.costRub.toLocaleString('ru-RU')} ₽
          {plan.costPartial ? ' · частичная' : ''}. По ценам, сохранённым в рецептах.</p>}
        <details open>
          <summary>Список покупок</summary>
          {dirty ? <p>Пересчитайте список после изменений.</p> : <>
            <ul>
              {plan.shopping.totals.map((item) => <li key={item.name + item.unit}>{item.name} — {Number(item.amount.toPrecision(5))} {item.unit}</li>)}
              {plan.shopping.to_taste.map((item, index) => <li key={index}>{item.name} — по вкусу ({item.source_recipe})</li>)}
              {plan.shopping.null_amounts.map((item, index) => <li key={index}>{item.name} — уточнить количество ({item.source_recipe})</li>)}
            </ul>
            {plan.manual.length > 0 && <p>Нужен ручной расчёт: {plan.manual.join(', ')}.</p>}
            {!plan.shopping.totals.length && !plan.shopping.to_taste.length && !plan.shopping.null_amounts.length && !plan.manual.length && <p>Покупки не требуются.</p>}
          </>}
        </details>
        {!dirty && plan.shopping.totals.length > 0 && (
          <StoreCart key={JSON.stringify(plan.shopping.totals)} items={plan.shopping.totals} send={sendStore} />
        )}
        <div className="plan-actions">
          <button disabled={!!pending || !dirty} onClick={() => generate('preview')}>Пересчитать покупки</button>
          <button className="primary" disabled={!!pending || !plan.entries.length || !!saved} onClick={() => generate('save')}>Сохранить в Obsidian</button>
        </div>
        {saved && <p role="status">Сохранено в «Планы питания» · {saved}</p>}
      </section>}
    </div>
  );
}
