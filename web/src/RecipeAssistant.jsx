import React, { useState } from 'react';
import { PlanningTags } from './PlanningTags.jsx';
import { PortionPrice, priceContextKey, storedPriceContext } from './PortionPrice.jsx';

const nutrientLabels = {
  kcal: 'ккал',
  protein_g: 'г белков',
  fat_g: 'г жиров',
  carbs_g: 'г углеводов',
};

export function Nutrition({ values }) {
  if (!Object.keys(values).length) return null;
  return (
    <section>
      <h2>Примерное КБЖУ на порцию</h2>
      <ul className="nutrition">
        {Object.entries(nutrientLabels).map(([key, label]) => (
          values[key] != null && <li key={key}><strong>{values[key]}</strong> {label}</li>
        ))}
      </ul>
    </section>
  );
}

export function RecipeAssistant({ send, apply, priceRequest, onClose, categories = {}, indexes = {}, tagLabels = {} }) {
  const isNew = Boolean(onClose);
  const [isOpen, setIsOpen] = useState(isNew);
  const [history, setHistory] = useState([]);
  const [proposal, setProposal] = useState(null);
  const [answer, setAnswer] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [index, setIndex] = useState('');
  const [priceContext, setPriceContext] = useState(storedPriceContext);

  async function updatePrice(context, replacement) {
    setPending(true);
    setError('');
    try {
      const links = Object.fromEntries((proposal.draft.portion_price?.items ?? [])
        .filter((item) => item.link).map((item) => [item.index, item.link]));
      if (replacement) links[replacement.index] = replacement.link;
      const value = await priceRequest('/api/recipes/portion-price', { ...context, draft: proposal.draft, links });
      setProposal({ ...proposal, draft: { ...proposal.draft, portion_price: value } });
      setPriceContext(context);
      localStorage.setItem(priceContextKey, JSON.stringify(context));
    } catch (failure) {
      setError(failure.message);
    } finally {
      setPending(false);
    }
  }

  async function ask(nextHistory) {
    setPending(true);
    setError('');
    try {
      const next = await send({ history: nextHistory, revision: nextHistory.length ? proposal?.revision : undefined,
        priceContext: storedPriceContext() });
      if (next.draft?.category !== proposal?.draft?.category) setIndex('');
      setProposal(next);
      setHistory([...nextHistory, { role: 'assistant', content: next.message, draft: next.draft }]);
      setAnswer('');
    } catch (failure) {
      setError(failure.message);
    } finally {
      setPending(false);
    }
  }

  async function submitAnswer(event) {
    event.preventDefault();
    if (!answer.trim() && (isNew || history.length)) return;
    const next = answer.trim() ? [...history, { role: 'user', content: answer.trim() }] : history;
    await ask(next);
  }

  async function saveProposal() {
    setPending(true);
    setError('');
    try {
      await apply({ draft: proposal.draft, revision: proposal.revision, index });
      setIsOpen(false);
      setSaved(true);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setPending(false);
    }
  }

  if (!isOpen) return (
    <div className="assistant-launch">
      <button type="button" onClick={() => {
        setIsOpen(true);
        setSaved(false);
        setError('');
        setHistory([]);
        setProposal(null);
        setAnswer('');
        ask([]);
      }}>Синхронизировать с AI</button>
      <small>Текст этой заметки будет отправлен в OpenRouter.</small>
      {saved && <p role="status">Рецепт на одну порцию сохранён в Obsidian.</p>}
    </div>
  );

  const draft = proposal?.draft;
  const tables = indexes[draft?.category] ?? [];
  return (
    <section className="assistant-chat" aria-label="Синхронизация рецепта">
      <div className="assistant-heading">
        <h2>{isNew ? 'Новый рецепт с AI' : 'AI-синхронизация'}</h2>
        <button type="button" disabled={pending} onClick={onClose ?? (() => setIsOpen(false))}>Закрыть</button>
      </div>
      <div role="log" aria-live="polite" className="chat-messages">
        {history.map(({ role, content }, index) => (
          <p className={role === 'user' ? 'chat-answer' : 'chat-message'} key={index}>
            <strong>{role === 'user' ? 'Вы' : 'AI'}</strong><br />{content}
          </p>
        ))}
      </div>
      {draft && (
        <div className="assistant-draft">
          <h2>{draft.title ?? 'Черновик на одну порцию'}</h2>
          {isNew && <p>{categories[draft.category]} · 1 порция</p>}
          <ul className="ingredients">
            {draft.ingredients.map((item, index) => (
              <li key={index}><span>{item.name}</span><span>{item.amount} {item.unit}</span></li>
            ))}
          </ul>
          <ol>{draft.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>
          <Nutrition values={draft.nutrition} />
          <PortionPrice value={draft.portion_price} context={priceContext} disabled={pending}
            send={(address) => priceRequest('/api/stores/lenta/hubs', { address })} onEstimate={updatePrice} />
          <PlanningTags labels={tagLabels} selected={draft.planningTags}
            onChange={(planningTags) => setProposal({ ...proposal, draft: { ...draft, planningTags } })} />
          {draft.assumptions.length > 0 && (
            <details open>
              <summary>Допущения AI</summary>
              <ul>{draft.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul>
            </details>
          )}
          {tables.length > 1 && (
            <label className="assistant-index">Таблица в Obsidian
              <select value={index} onChange={(event) => setIndex(event.target.value)}>
                <option value="">Выберите таблицу</option>
                {tables.map((table) => <option key={table}>{table}</option>)}
              </select>
            </label>
          )}
          <button className="primary" type="button"
            disabled={pending || !!answer.trim() || (tables.length > 1 && !index)}
            onClick={saveProposal}>{isNew ? 'Сохранить рецепт' : 'Применить к заметке'}</button>
        </div>
      )}
      <form className="chat-reply" onSubmit={submitAnswer}>
        <textarea aria-label={isNew && !history.length ? 'Текст рецепта или название блюда' : 'Ответ или правка'}
          placeholder={isNew && !history.length ? 'Вставьте текст рецепта или напишите «Добавь шакшуку»…' : 'Ответьте на вопрос или предложите правку…'}
          value={answer} onChange={(event) => setAnswer(event.target.value)} rows={isNew && !history.length ? 6 : 2} maxLength={isNew && !history.length ? 24000 : 4000} disabled={pending} />
        {isNew && !history.length && <small>Этот текст будет отправлен в OpenRouter.</small>}
        <button disabled={pending || (!answer.trim() && (isNew || history.length > 0))}>{isNew || history.length ? 'Отправить' : 'Повторить'}</button>
      </form>
      {pending && <p role="status">Ожидаем ответ…</p>}
      {error && <p role="alert" className="error">{error}</p>}
    </section>
  );
}
