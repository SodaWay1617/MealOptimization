import React, { useEffect, useRef, useState } from 'react';
import Markdown from 'react-markdown';

function wikilinks(recipes) {
  return () => function transform(node) {
    if (!node.children || node.type === 'link') return;
    node.children = node.children.flatMap((child) => {
      if (child.type !== 'text') {
        transform(child);
        return [child];
      }
      const parts = [];
      let position = 0;
      for (const match of child.value.matchAll(/\[\[([^\]\r\n|]+)(?:\|([^\]\r\n]+))?\]\]/g)) {
        const key = match[1].trim();
        const matches = recipes.filter(({ id, title }) => title === key || id === key || id.split('/').at(-1).slice(0, -3) === key);
        if (matches.length !== 1) continue;
        if (match.index > position) parts.push({ type: 'text', value: child.value.slice(position, match.index) });
        parts.push({ type: 'link', url: '/recipe?' + new URLSearchParams({ id: matches[0].id }),
          children: [{ type: 'text', value: match[2] ?? key }] });
        position = match.index + match[0].length;
      }
      if (!parts.length) return [child];
      if (position < child.value.length) parts.push({ type: 'text', value: child.value.slice(position) });
      return parts;
    });
  };
}

function recipeIdFor(href, recipes) {
  if (href?.startsWith('/recipe?')) return new URLSearchParams(href.split('?')[1]).get('id');
  try {
    const id = decodeURIComponent(href ?? '').match(/^(?:\.\.\/)+Рецепты\/(.+\.md)$/)?.[1];
    return recipes.some((recipe) => recipe.id === id) ? id : null;
  } catch {
    return null;
  }
}

export function PlanArchive({ active, request, saved, recipes, onOpenRecipe, onCreate }) {
  const [plans, setPlans] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const article = useRef(null);

  useEffect(() => {
    if (active && selected) article.current?.scrollIntoView({ block: 'start' });
  }, [active, selected]);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    request('/api/plans', { signal: controller.signal })
      .then((result) => setPlans(result.plans))
      .catch((failure) => { if (failure.name !== 'AbortError') setError(failure.message); });
    return () => controller.abort();
  }, [active, request, saved]);

  async function openPlan(id) {
    setLoading(true);
    setError('');
    try {
      setSelected(await request('/api/plan?' + new URLSearchParams({ id })));
    } catch (failure) {
      setError(failure.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel plan-archive">
      <div className="plan-archive-heading">
        <h1>План питания</h1>
        <button className="primary" onClick={() => { setSelected(null); onCreate(); }}>Создать план</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {loading && <p role="status">Открываем план…</p>}
      {selected ? (
        <article className="saved-plan" ref={article}>
          <button onClick={() => setSelected(null)}>← Сохранённые планы</button>
          <h2>{selected.title}</h2>
          <Markdown remarkPlugins={[wikilinks(recipes)]} components={{
            a: ({ href, children }) => {
              const id = recipeIdFor(href, recipes);
              return id ? <a href={href} onClick={(event) => { event.preventDefault(); onOpenRecipe(id); }}>{children}</a>
                : <a href={href}>{children}</a>;
            },
          }}>{selected.body}</Markdown>
        </article>
      ) : <>
        <h2>Сохранённые планы</h2>
        {!plans && !error && <p role="status">Загружаем планы…</p>}
        {plans?.length === 0 && <p>В Obsidian пока нет сохранённых планов.</p>}
        <ul className="saved-plans">
          {plans?.map((plan) => <li key={plan.id}><button disabled={loading} onClick={() => openPlan(plan.id)}>{plan.title} <span aria-hidden="true">↗</span></button></li>)}
        </ul>
      </>}
    </section>
  );
}
