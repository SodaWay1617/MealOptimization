import React, { useEffect, useState } from 'react';
import { ingredientKey, readPreference, shops, writePreference } from './shoppingPreferences.js';

const units = { г: ['г', 1], кг: ['г', 1000], мл: ['мл', 1], л: ['мл', 1000], шт: ['шт', 1] };
const rubles = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' });

function lineCost(row) {
  const product = row.products.find((item) => item.id === row.id);
  if (!Number.isFinite(product?.price) || product.price <= 0) return null;
  const packs = product.unit === 'quanta' ? Number(row.q) / product.limit.step : Number(row.q);
  return Math.round(product.price * packs * 100);
}

function quantityFor(ingredient, product) {
  const required = units[ingredient.unit];
  if (!required) return '';
  const amount = ingredient.amount * required[1];
  if (product.unit === 'quanta' && required[0] === 'г' && product.limit.step === 1) {
    return Math.max(product.limit.min, Math.ceil(amount / product.weightGrams - 1e-10));
  }
  if (product.unit === 'кг' && required[0] === 'г') return Math.ceil(amount / 10) / 100;
  if (product.unit !== 'шт') return '';
  const declared = Array.from(`${product.package ?? ''} ${product.name}`.matchAll(/(\d+(?:[.,]\d+)?)\s*(кг|мл|шт|г|л)(?=\.?($|[\s,;)×]))/gi))
    .map((match) => [Number(match[1].replace(',', '.')), units[match[2].toLowerCase()]])
    .find(([, unit]) => unit?.[0] === required[0]);
  const weight = units[product.weight?.unit];
  const packageSize = declared ? declared[0] * declared[1][1]
    : required[0] === 'г' && weight?.[0] === 'г' ? Number(product.weight.value) * weight[1] : 0;
  return packageSize > 0 ? Math.ceil(amount / packageSize - 1e-10) : '';
}

export function StoreCart({ items, send }) {
  const [initialContext] = useState(() => readPreference('shopping-context', {}));
  const [store, setStore] = useState(initialContext.store ?? 'vkusvill');
  const [rows, setRows] = useState([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [link, setLink] = useState('');
  const [address, setAddress] = useState(initialContext.address ?? '');
  const [hubs, setHubs] = useState(initialContext.hubs ?? []);
  const [storeId, setStoreId] = useState(initialContext.storeId ?? '');
  const [channel, setChannel] = useState(initialContext.channel ?? 'lo');
  const [instruction, setInstruction] = useState('');
  const isLenta = store === 'lenta';
  const context = isLenta ? { storeId: Number(storeId), channel } : {};
  useEffect(() => {
    writePreference('shopping-context', { store, address, hubs, storeId, channel });
  }, [store, address, hubs, storeId, channel]);

  function clearResults() {
    setRows([]);
    setLink('');
    setError('');
  }

  async function lookupHubs(event) {
    event.preventDefault();
    clearResults();
    setStoreId('');
    setHubs([]);
    setPending(true);
    try {
      const result = await send(store, 'hubs', { address });
      setHubs(result.hubs);
      if (!result.hubs.length) setError('Магазины не найдены. Уточните город, улицу и номер дома.');
      if (result.hubs.length === 1) setStoreId(result.hubs[0].id);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setPending(false);
    }
  }

  function update(index, change) {
    setLink('');
    setRows((current) => current.map((row, position) => position === index ? { ...row, ...change } : row));
  }

  function preferredLinks(row) {
    return (readPreference('shopping-links', {})[store]?.[ingredientKey(row.ingredient.name)] ?? [])
      .map((link) => link.trim()).filter(Boolean);
  }

  function isCompatible(row, product) {
    const q = quantityFor(row.ingredient, product);
    return q !== '' && (typeof product.stock !== 'number' || q <= product.stock)
      && (!product.limit || q <= product.limit.max);
  }

  async function findProducts(row, queries = [row.query]) {
    try {
      const collected = new Map();
      for (const [position, query] of queries.entries()) {
        const preferred = position === 0 ? preferredLinks(row) : [];
        const result = await send(store, 'search', { query, preferred, ...context });
        for (const product of result.products) {
          if (!collected.has(product.id)) collected.set(product.id, product);
        }
        if ([...collected.values()].some((product) => product.preferred && isCompatible(row, product))) break;
      }
      const word = ingredientKey(row.query).match(/[а-яёa-z]{3,}/i)?.[0];
      const root = word?.startsWith('помид') ? 'томат' : word?.slice(0, 4);
      const products = [...collected.values()].slice(0, 16);
      const suggested = products.find((product) => product.preferred && isCompatible(row, product))
        ?? products.find((product) => {
          const name = ingredientKey(product.name);
          return root && (name.includes(root) || name.includes(word.slice(0, 4)))
            && (!word.startsWith('кабач') || !/семен|икра|рассад/.test(name)) && isCompatible(row, product);
        });
      return { products, id: suggested?.id ?? '', q: suggested ? quantityFor(row.ingredient, suggested) : '', error: '' };
    } catch (failure) {
      return { products: [], id: '', q: '', error: failure.message };
    }
  }

  async function lookupAll(ai = false) {
    setPending(true);
    setError('');
    setLink('');
    try {
      const rules = readPreference('shopping-rules', '');
      const aiPlan = ai ? await send(store, 'ai-queries', { items, instruction, rules }) : null;
      const initial = [...items, ...(aiPlan?.extras ?? [])].map((ingredient) => ({
        ingredient, query: ingredient.name, products: [], id: '', q: '', error: '',
      }));
      setRows(initial);
      const found = [...initial];
      let next = 0;
      await Promise.all(Array.from({ length: Math.min(3, initial.length) }, async () => {
        while (next < initial.length) {
          const index = next++;
          const row = initial[index];
          const planned = aiPlan?.queries[index] ?? [];
          const query = ingredientKey(row.query).replace(/^помидор(?:ы)?(?=\s|$)/, 'томаты');
          const result = await findProducts(row, [...new Set([...planned, query])].slice(0, 3));
          found[index] = { ...row, ...result };
          update(index, result);
        }
      }));
      if (ai) {
        const { ids } = await send(store, 'ai-rank', {
          rules, instruction, rows: found.map((row) => ({
            ingredient: row.ingredient,
            products: row.products.map((product) => ({
              id: product.id, name: product.name, package: product.package,
              price: product.price, stock: product.stock, quantity: quantityFor(row.ingredient, product),
              preferred: product.preferred,
            })),
          })),
        });
        found.forEach((row, index) => {
          if (row.products.some((product) => product.id === row.id && product.preferred)) return;
          const chosen = row.products.find((product) => product.id === ids[index]);
          update(index, { id: chosen?.id ?? '', q: chosen ? quantityFor(row.ingredient, chosen) : '' });
        });
      }
    } catch (failure) {
      setError(failure.message);
    } finally {
      setPending(false);
    }
  }

  async function lookupOne(event, index) {
    event.preventDefault();
    const row = rows[index];
    if (!row.query.trim()) return;
    setPending(true);
    try {
      update(index, await findProducts(row));
    } finally {
      setPending(false);
    }
  }

  async function selectProduct(index, id) {
    const row = rows[index];
    const product = row.products.find((item) => item.id === id);
    if (!product) return update(index, { id: '', q: '', error: '' });
    if (!isLenta || product.unit) return update(index, { id, q: quantityFor(row.ingredient, product), error: '' });
    setPending(true);
    try {
      const result = await send(store, 'details', { id, ...context });
      const resolved = { ...product, ...result.product };
      update(index, { id, q: quantityFor(row.ingredient, resolved), error: '',
        products: row.products.map((item) => item.id === id ? resolved : item) });
    } catch (failure) {
      update(index, { error: failure.message });
    } finally {
      setPending(false);
    }
  }

  const selected = rows.filter((row) => {
    if (!row.id) return false;
    const quantity = Number(row.q);
    if (!isLenta) return quantity >= 0.01 && quantity <= 40;
    const limit = row.products.find((product) => product.id === row.id)?.limit;
    return Number.isInteger(quantity) && quantity >= (limit?.min ?? 1)
      && quantity <= (limit?.max ?? 1000000) && quantity % (limit?.step ?? 1) === 0;
  });
  const invalid = rows.some((row) => row.id && !selected.includes(row));
  const costs = isLenta ? selected.map(lineCost) : [];
  const priced = costs.filter((cost) => cost != null);
  const subtotal = priced.reduce((sum, cost) => sum + cost, 0) / 100;

  async function makeLink() {
    setPending(true);
    setError('');
    try {
      const result = await send(store, 'cart', {
        products: selected.map((row) => ({ id: row.id, q: Number(row.q) })),
      });
      setLink(result.link);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="store-cart" aria-label="Корзина магазина">
      <h3>Корзина магазина</h3>
      <div className="plan-actions">
        <label>Магазин <select value={store} disabled={pending} onChange={(event) => {
          setStore(event.target.value); clearResults();
        }}>
          {shops.map((shop) => <option key={shop.id} value={shop.id}>{shop.name}</option>)}
        </select></label>
        <button type="button" disabled={pending || !items.length || (isLenta && !storeId)} onClick={() => lookupAll()}>Подобрать товары</button>
        <button type="button" disabled={pending || !items.length || (isLenta && !storeId)} onClick={() => lookupAll(true)}>AI-подбор продуктов</button>
      </div>
      <label className="cart-instruction">Пожелания на эту покупку
        <textarea rows={2} maxLength={4000} disabled={pending} value={instruction}
          onChange={(event) => setInstruction(event.target.value)} placeholder="Сегодня экономим. Добавь 1 кг томатов." />
      </label>
      {isLenta && <>
        <form className="plan-actions" onSubmit={lookupHubs}>
          <label>Адрес для поиска магазинов <input value={address} maxLength={180}
            disabled={pending} onChange={(event) => {
              setAddress(event.target.value); setHubs([]); setStoreId(''); clearResults();
            }} placeholder="Город, улица, дом" /></label>
          <button disabled={pending || address.trim().length < 3}>Найти магазины</button>
        </form>
        <p><small>Адрес передаётся Ленте для поиска ближайших магазинов.</small></p>
        {hubs.length > 0 && <div className="plan-actions">
          <label>Магазин Ленты <select value={storeId} disabled={pending} onChange={(event) => {
            setStoreId(Number(event.target.value) || ''); clearResults();
          }}>
            <option value="">Выберите магазин</option>
            {hubs.map((hub) => <option key={hub.id} value={hub.id}>{hub.address}</option>)}
          </select></label>
          <label>Получение <select value={channel} disabled={pending} onChange={(event) => {
            setChannel(event.target.value); clearResults();
          }}>
            <option value="lo">Доставка</option><option value="locc">Самовывоз</option>
          </select></label>
        </div>}
      </>}
      <p><small>Проверьте фасовку и количество. Наличие по вашему адресу уточняется после перехода в магазин.</small></p>
      {pending && <p role="status">Загружаем данные магазина…</p>}
      {rows.map((row, index) => {
        const product = row.products.find((item) => item.id === row.id);
        return (
          <fieldset key={index} disabled={pending} className="cart-row">
            <legend>{row.ingredient.name} · {Number(row.ingredient.amount.toPrecision(5))} {row.ingredient.unit}</legend>
            <form className="plan-actions" onSubmit={(event) => lookupOne(event, index)}>
              <input aria-label={`Поиск товара для ${row.ingredient.name}`} value={row.query} maxLength={180}
                onChange={(event) => update(index, { query: event.target.value })} />
              <button disabled={!row.query.trim()}>Найти</button>
            </form>
            <label>Товар <select value={row.id} onChange={(event) => selectProduct(index, Number(event.target.value) || '')}>
              <option value="">Пропустить позицию</option>
              {row.products.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select></label>
            {product && <label>Количество{product.unit === 'quanta' ?
              (product.limit.step === 1 ? ` · по ${product.weightGrams} г` : ` · шаг ${product.limit.step}`)
              : product.unit ? `, ${product.unit}` : ''}
              <input type="number" value={row.q} min={product.limit?.min ?? (isLenta ? 1 : 0.01)}
                max={product.limit?.max ?? (isLenta ? 1000000 : 40)} step={product.limit?.step ?? (isLenta ? 1 : 0.01)}
                onChange={(event) => update(index, { q: event.target.value })} />
            </label>}
            {product?.url && <a href={product.url} target="_blank" rel="noreferrer">Открыть товар</a>}
            {isLenta && selected.includes(row) && (
              <span>{lineCost(row) == null ? 'Цена недоступна' : rubles.format(lineCost(row) / 100)}</span>
            )}
            {row.error && <p className="error" role="alert">{row.error}</p>}
            {!pending && !row.error && !row.products.length && <small>Товары не найдены. Попробуйте изменить запрос.</small>}
          </fieldset>
        );
      })}
      {rows.length > 0 && <div className="plan-actions">
        <span>Выбрано {selected.length} из {rows.length}</span>
        <button className="primary" type="button" disabled={pending || invalid || !selected.length}
          onClick={makeLink}>Создать ссылку на корзину</button>
      </div>}
      {isLenta && selected.length > 0 && <div className="cart-total">
        {priced.length > 0
          ? <p><strong>{priced.length < selected.length ? 'Частичная сумма товаров' : 'Сумма выбранных товаров'} · {rubles.format(subtotal)}</strong></p>
          : <p>Сумма товаров недоступна.</p>}
        {priced.length < selected.length && <p>Без цены: {selected.length - priced.length} из {selected.length} позиций.</p>}
        <small>По ценам выбранного магазина, без доставки и персональных скидок. Итог к оплате покажет Лента по ссылке на корзину.</small>
      </div>}
      {error && <p role="alert" className="error">{error}</p>}
      {link && <p><a href={link} target="_blank" rel="noreferrer">{isLenta ? 'Открыть корзину в Ленте' : 'Открыть корзину во ВкусВилле'}</a></p>}
    </section>
  );
}
