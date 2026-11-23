import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { imageUrl, RecipeCover, RecipeMarkdown } from './RecipeMarkdown.jsx';
import { Nutrition, RecipeAssistant } from './RecipeAssistant.jsx';
import { RecipeForm } from './RecipeForm.jsx';
import { MealPlan } from './MealPlan.jsx';
import { ShoppingPreferences } from './ShoppingPreferences.jsx';
import { PlanningTags } from './PlanningTags.jsx';
import './styles.css';

async function request(path, options) {
  const response = await fetch(path, options);
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || 'Не удалось выполнить запрос.');
  return result;
}

function postJson(path, payload) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

const rubles = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' });
const nutrientNumber = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
const catalogCategoryOrder = ['breakfast', 'salad', 'soup', 'main', 'snack', 'drink'];
const catalogNutrients = {
  kcal: ['Калорийность', 'ккал'],
  protein_g: ['Белки', 'Б'],
  fat_g: ['Жиры', 'Ж'],
  carbs_g: ['Углеводы', 'У'],
};

function CardNutrition({ values = {} }) {
  const entries = Object.entries(catalogNutrients).filter(([key]) => values[key] != null);
  if (!entries.length) return null;
  return <small className="card-nutrition" aria-label="Примерное КБЖУ на порцию">
    {entries.map(([key, [name, label]]) => (
      <span key={key} title={name}>
        {key === 'kcal' ? `${nutrientNumber.format(values[key])} ${label}` : `${label} ${nutrientNumber.format(values[key])} г`}
      </span>
    ))}
  </small>;
}

function CatalogCard({ item, onOpen }) {
  return (
    <button className={item.previewImage ? 'recipe-card' : 'recipe-card recipe-card-compact'} onClick={() => onOpen(item)}>
      {item.previewImage && <img className="recipe-preview" src={imageUrl(item.id, item.previewImage)}
        alt="" loading="lazy" decoding="async" />}
      <span className="recipe-card-content">
        <strong>{item.title}</strong>
        {item.planningTags.includes('budget') && <span className="category">Недорогое</span>}
        {item.portionPrice?.rub != null && <small>
          {item.portionPrice.missing.length > 0 ? 'Частично: ' : 'За порцию: '}{rubles.format(item.portionPrice.rub)}
        </small>}
        <CardNutrition values={item.nutrition} />
        {item.servings != null && <small>{item.servings} порц.</small>}
      </span>
      <span className="recipe-card-arrow" aria-hidden="true">↗</span>
    </button>
  );
}

function RecipeDetail({ recipe, categoryLabel, onSaved, tagLabels }) {
  const query = new URLSearchParams({ id: recipe.id });
  const [tags, setTags] = useState(recipe.planningTags ?? []);
  const [tagStatus, setTagStatus] = useState('');
  const [recipeSection, setRecipeSection] = useState('ingredients');
  const [cookingStep, setCookingStep] = useState(null);
  const hasStructuredRecipe = recipe.ingredients.length > 0 && recipe.steps?.length > 0;
  const workspace = useRef(null);
  async function saveRecipeTags() {
    setTagStatus('');
    try {
      onSaved(await postJson(`/api/recipe/tags?${query}`, tags));
      setTagStatus('Теги сохранены.');
    } catch (error) {
      setTagStatus(error.message);
    }
  }
  function postAssistant(action, payload) {
    return postJson(`/api/recipe/assistant${action}?${query}`, payload);
  }
  return (
    <article className="recipe recipe-detail">
      <header className="recipe-intro">
        <div>
          {categoryLabel && <p className="category">{categoryLabel}</p>}
          <h1>{recipe.title}</h1>
          {recipe.servings && <p className="category">{recipe.servings} порц.</p>}
          {!recipe.isSynced && <small>Для плана питания нужна AI-синхронизация</small>}
          {hasStructuredRecipe && <div className="cook-actions"><button className="primary" onClick={() => {
            setCookingStep(0);
            setRecipeSection('steps');
            workspace.current?.scrollIntoView({ block: 'start' });
          }}>Начать готовить</button></div>}
        </div>
        <RecipeCover recipe={recipe} />
      </header>
      <div className="recipe-stats">
      <dl className="recipe-price">
        <dt>Цена порции</dt>
        <dd>{recipe.portionPrice?.rub == null ? 'Без оценки' : <>
          <strong>{rubles.format(recipe.portionPrice.rub)}</strong>
          <small>Лента · {recipe.portionPrice.date}{recipe.portionPrice.missing.length > 0 ? ' · частичная оценка' : ''}</small>
        </>}</dd>
      </dl>
        <Nutrition values={recipe.nutrition ?? {}} />
      </div>
      {hasStructuredRecipe && (
        <section className="panel recipe-workspace" ref={workspace}>
          <nav className="recipe-sections" aria-label="Разделы рецепта">
            <button aria-pressed={recipeSection === 'ingredients'} onClick={() => setRecipeSection('ingredients')}>Ингредиенты</button>
            <button aria-pressed={recipeSection === 'steps'} onClick={() => setRecipeSection('steps')}>Приготовление</button>
          </nav>
          {recipeSection === 'ingredients' ? (
            <ul className="ingredients">
              {recipe.ingredients.map((item, index) => (
                <li key={index}><span>{item.name}</span><strong>{item.amount} {item.unit}</strong></li>
              ))}
            </ul>
          ) : cookingStep == null ? (
            <ol className="cooking-steps">{recipe.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>
          ) : (
            <div className="cooking-current">
              <p className="category">Шаг {cookingStep + 1} из {recipe.steps.length}</p>
              <progress value={cookingStep + 1} max={recipe.steps.length} aria-label="Ход приготовления" />
              <p aria-live="polite">{recipe.steps[cookingStep]}</p>
              <div className="plan-actions">
                <button disabled={cookingStep === 0} onClick={() => setCookingStep(cookingStep - 1)}>Назад</button>
                <button className="primary" onClick={() => setCookingStep(cookingStep + 1 < recipe.steps.length ? cookingStep + 1 : null)}>
                  {cookingStep + 1 < recipe.steps.length ? 'Дальше' : 'Завершить'}
                </button>
                <button onClick={() => setCookingStep(null)}>Все шаги</button>
              </div>
            </div>
          )}
        </section>
      )}
      {!hasStructuredRecipe && recipe.ingredients.length > 0 && <section className="panel">
        <h2>Ингредиенты</h2>
        <ul className="ingredients">{recipe.ingredients.map((item, index) => (
          <li key={index}><span>{item.name}</span><strong>{item.amount} {item.unit}</strong></li>
        ))}</ul>
      </section>}
      {hasStructuredRecipe ? <details className="panel recipe-note"><summary>Заметка Obsidian</summary><RecipeMarkdown recipe={recipe} /></details>
        : <div className="panel recipe-note"><RecipeMarkdown recipe={recipe} /></div>}
      <section className="panel recipe-tools">
      <RecipeAssistant key={recipe.id} tagLabels={tagLabels} priceRequest={postJson}
        send={(payload) => postAssistant('', payload)} apply={async (payload) => {
        const saved = await postAssistant('/save', payload);
        setTags(saved.planningTags);
        setCookingStep(null);
        setRecipeSection('ingredients');
        onSaved(saved);
      }} />
      <details className="recipe-tags">
        <summary>Теги{tags.length > 0 ? ' · ' + tags.map((tag) => tagLabels[tag]).join(', ') : ''}</summary>
        <PlanningTags labels={tagLabels} selected={tags} onChange={setTags} />
        <button onClick={saveRecipeTags}>Сохранить теги</button>
        {tagStatus && <p role="status">{tagStatus}</p>}
      </details>
      </section>
    </article>
  );
}

function App() {
  const [catalog, setCatalog] = useState(null);
  const [recipe, setRecipe] = useState(null);
  const [screen, setScreen] = useState('catalog');
  const [returnToPlan, setReturnToPlan] = useState(false);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [status, setStatus] = useState('');
  const searchInput = useRef(null);

  async function refreshCatalog(signal) {
    const next = await request('/api/recipes', { signal });
    setCatalog(next);
  }

  useEffect(() => {
    const controller = new AbortController();
    refreshCatalog(controller.signal).catch((error) => {
      if (error.name !== 'AbortError') setStatus(error.message);
    });
    return () => controller.abort();
  }, []);

  async function navigate(action) {
    setStatus('');
    try {
      await action();
    } catch (error) {
      setStatus(error.message);
    }
  }

  const categories = catalog?.categories ?? {};
  const orderedCategoryKeys = [...new Set([...catalogCategoryOrder, ...Object.keys(categories)])]
    .filter((key) => Object.hasOwn(categories, key));
  const tagLabels = catalog?.planningTags ?? {};
  const search = query.trim().toLocaleLowerCase('ru');
  const recipes = (catalog?.recipes ?? []).filter((item) => (
    (!category || item.category === category) &&
    [item.title, ...item.ingredients.map(({ name }) => name)]
      .some((value) => value.toLocaleLowerCase('ru').includes(search))
  ));
  const groupedRecipes = new Map([...orderedCategoryKeys, null].map((key) => [key, []]));
  for (const item of recipes) {
    groupedRecipes.get(groupedRecipes.has(item.category) ? item.category : null).push(item);
  }
  const featured = catalog?.recipes.find((item) => item.previewImage && item.isSynced)
    ?? catalog?.recipes.find((item) => item.previewImage);

  function openCatalogRecipe(item) {
    return navigate(async () => {
      setRecipe(await request('/api/recipe?' + new URLSearchParams({ id: item.id })));
      setReturnToPlan(false);
      setScreen('detail');
      window.scrollTo(0, 0);
    });
  }

  return (
    <>
      <header className="topbar">
        <div className="shell topbar-content">
          <button className="brand" onClick={() => { setScreen('catalog'); setStatus(''); }}>
            <span className="brand-icon" aria-hidden="true">М</span> Мои рецепты
          </button>
          {catalog && (
            <div className="topbar-actions">
              <button onClick={() => { setScreen('plan'); setStatus(''); }}>План питания</button>
              <button onClick={() => { setScreen('preferences'); setStatus(''); }}>Предпочтения</button>
              <button onClick={() => { setScreen('new'); setStatus(''); }}>＋ Добавить рецепт</button>
              <button className="primary" onClick={() => { setScreen('new-ai'); setStatus(''); }}>Добавить рецепт с AI</button>
            </div>
          )}
        </div>
      </header>
      <main className="shell">
        {status && <p role="alert" className="error">{status}</p>}
        {screen !== 'catalog' && (
          <button className="back" onClick={() => { setScreen(screen === 'detail' && returnToPlan ? 'plan' : 'catalog'); setStatus(''); }}>
            {screen === 'detail' && returnToPlan ? '← К плану питания' : '← Все рецепты'}
          </button>
        )}
        {catalog && <div hidden={screen !== 'plan'}>
          <MealPlan active={screen === 'plan'} categories={categories} tags={tagLabels} recipes={catalog.recipes}
            request={request} send={(payload) => postJson('/api/plans', payload)}
            sendStore={(store, action, payload) => postJson(`/api/stores/${store}/${action}`, payload)}
            onOpenRecipe={(id) => navigate(async () => {
              setRecipe(await request('/api/recipe?' + new URLSearchParams({ id })));
              setReturnToPlan(true);
              setScreen('detail');
            })} />
        </div>}
        {screen === 'preferences' && <ShoppingPreferences recipes={catalog.recipes} />}
        {screen === 'new' && (
          <RecipeForm categories={categories} indexes={catalog.indexes ?? {}} tagLabels={tagLabels} onSave={async (draft) => {
            const saved = await postJson('/api/recipes', draft);
            setRecipe(saved);
            setReturnToPlan(false);
            setScreen('detail');
            await navigate(refreshCatalog);
          }} />
        )}
        {screen === 'new-ai' && (
          <RecipeAssistant categories={categories} indexes={catalog.indexes ?? {}} tagLabels={tagLabels} priceRequest={postJson}
            onClose={() => setScreen('catalog')}
            send={(payload) => postJson('/api/recipes/assistant', payload)}
            apply={async (payload) => {
              const saved = await postJson('/api/recipes/assistant/save', payload);
              setRecipe(saved);
              setReturnToPlan(false);
              setScreen('detail');
              await navigate(refreshCatalog);
            }} />
        )}
        {screen === 'detail' && recipe && (
          <RecipeDetail key={recipe.id} recipe={recipe} categoryLabel={categories[recipe.category]} tagLabels={tagLabels} onSaved={(saved) => {
            setRecipe(saved);
            navigate(refreshCatalog);
          }} />
        )}
        {screen === 'catalog' && (
          <>
            <section className={featured ? 'catalog-intro has-featured' : 'catalog-intro'}>
              <div className="catalog-intro-copy">
                <h1>Книга рецептов</h1>
                <div className="catalog-actions">
                  <button className="primary" onClick={() => { setScreen('plan'); window.scrollTo(0, 0); }}>Спланировать меню</button>
                  <button onClick={() => searchInput.current?.focus()}>Найти рецепт</button>
                </div>
              </div>
              {featured && <button className="catalog-feature" onClick={() => openCatalogRecipe(featured)}>
                <img src={imageUrl(featured.id, featured.previewImage)} alt="" />
                <span>{featured.title} <span aria-hidden="true">↗</span></span>
              </button>}
            </section>
            <div className="filters">
              <input ref={searchInput} type="search" aria-label="Поиск рецептов" placeholder="Поиск по названию или ингредиенту" value={query} onChange={(event) => setQuery(event.target.value)} />
              <select aria-label="Категория" value={category} onChange={(event) => setCategory(event.target.value)}>
                <option value="">Все категории</option>
                {orderedCategoryKeys.map((key) => <option key={key} value={key}>{categories[key]}</option>)}
              </select>
              <button onClick={() => navigate(refreshCatalog)}>Обновить</button>
            </div>
            {!search && !category && <nav className="catalog-index" aria-label="Категории рецептов">
              {[...groupedRecipes].filter(([key, items]) => key && items.length).map(([key]) => (
                <a key={key} href={`#recipes-${key}`}>{categories[key]}</a>
              ))}
            </nav>}
            {!catalog && !status && <p role="status">Загрузка рецептов…</p>}
            {catalog && recipes.length === 0 && (
              <div className="panel empty">
                <h2>{query || category ? 'Рецепты не найдены' : 'Здесь будут ваши рецепты'}</h2>
                <p>{query || category ? 'Измените запрос или категорию.' : 'Добавьте рецепт через форму или положите Markdown-файлы в подключённую папку и обновите каталог.'}</p>
              </div>
            )}
            {[...groupedRecipes].filter(([, items]) => items.length > 0).map(([key, items]) => {
              const illustrated = items.filter((item) => item.previewImage);
              const compact = items.filter((item) => !item.previewImage);
              return (
                <section className="catalog-category" id={`recipes-${key ?? 'uncategorized'}`} key={key ?? 'uncategorized'}>
                  <h2>{categories[key] ?? 'Без категории'}</h2>
                  {illustrated.length > 0 && <div className="cards">
                    {illustrated.map((item) => <CatalogCard key={item.id} item={item} onOpen={openCatalogRecipe} />)}
                  </div>}
                  {compact.length > 0 && <div className="compact-cards">
                    {compact.map((item) => <CatalogCard key={item.id} item={item} onOpen={openCatalogRecipe} />)}
                  </div>}
                </section>
              );
            })}
          </>
        )}
      </main>
    </>
  );
}

createRoot(document.getElementById('root')).render(<App />);
