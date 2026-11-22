import React, { useState } from 'react';
import { PlanningTags } from './PlanningTags.jsx';

function newIngredient() {
  return { id: crypto.randomUUID(), name: '', amount: '', unit: 'г' };
}

export function RecipeForm({ categories, indexes, tagLabels, onSave }) {
  const [ingredients, setIngredients] = useState(() => [newIngredient()]);
  const [category, setCategory] = useState('');
  const [planningTags, setPlanningTags] = useState([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  function updateIngredient(id, changes) {
    setIngredients((items) => items.map((item) => item.id === id ? { ...item, ...changes } : item));
  }

  async function submitRecipe(event) {
    event.preventDefault();
    const fields = Object.fromEntries(new FormData(event.currentTarget));
    setPending(true);
    setError('');
    try {
      await onSave({
        ...fields,
        planningTags,
        servings: Number(fields.servings),
        ingredients: ingredients.map(({ name, amount, unit }) => ({
          name, amount: unit === 'по вкусу' ? null : Number(amount), unit,
        })),
      });
    } catch (failure) {
      setError(failure.message);
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="panel recipe-form" onSubmit={submitRecipe}>
      <h1>Новый рецепт</h1>
      <label>Название<input name="title" required maxLength={150} /></label>
      <div className="form-row">
        <label>Категория<select name="category" required value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="">Выберите категорию</option>
          {Object.entries(categories).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <label>Порции<input name="servings" type="number" min="1" max="1000" defaultValue="2" required /></label>
      </div>
      <PlanningTags labels={tagLabels} selected={planningTags} onChange={setPlanningTags} />
      {(indexes[category]?.length ?? 0) > 1 && (
        <label>Таблица в Obsidian<select key={category} name="index" required defaultValue="">
          <option value="">Выберите таблицу</option>
          {indexes[category].map((index) => <option key={index}>{index}</option>)}
        </select></label>
      )}
      <fieldset>
        <legend>Ингредиенты</legend>
        {ingredients.map((item, index) => (
          <div className="ingredient-row" key={item.id}>
            <input aria-label={`Ингредиент ${index + 1}`} placeholder="Название" required value={item.name} onChange={(event) => updateIngredient(item.id, { name: event.target.value })} />
            <input aria-label={`Количество ${index + 1}`} placeholder="Кол-во" type="number" step="any" min="0" required={item.unit !== 'по вкусу'} disabled={item.unit === 'по вкусу'} value={item.amount} onChange={(event) => updateIngredient(item.id, { amount: event.target.value })} />
            <select aria-label={`Единица ${index + 1}`} value={item.unit} onChange={(event) => updateIngredient(item.id, { unit: event.target.value })}>
              {['г', 'мл', 'шт', 'по вкусу'].map((unit) => <option key={unit}>{unit}</option>)}
            </select>
            <button type="button" aria-label={`Удалить ингредиент ${index + 1}`} disabled={ingredients.length === 1} onClick={() => setIngredients((items) => items.filter(({ id }) => id !== item.id))}>×</button>
          </div>
        ))}
        <button type="button" onClick={() => setIngredients((items) => [...items, newIngredient()])}>＋ Ингредиент</button>
      </fieldset>
      <label>Приготовление<textarea name="body" rows="7" required placeholder="1. Подготовьте ингредиенты…" /></label>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="primary" disabled={pending}>{pending ? 'Сохраняем…' : 'Сохранить рецепт'}</button>
    </form>
  );
}
