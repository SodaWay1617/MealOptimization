import React, { useState } from 'react';

export const priceContextKey = 'meal-planner:lenta-price-context';
const reasons = {
  not_found: 'Подходящий товар не найден',
  unavailable: 'Лента не вернула данные для выбранного магазина',
  no_price: 'У найденных товаров нет цены',
  unit: 'Не удалось пересчитать фасовку в единицы рецепта',
};

export function storedPriceContext() {
  try {
    const value = JSON.parse(localStorage.getItem(priceContextKey));
    return Number.isInteger(value?.storeId) && value.storeId > 0 && ['lo', 'locc'].includes(value.channel)
      ? value : null;
  } catch {
    return null;
  }
}

export function PortionPrice({ value, context, disabled, send, onEstimate }) {
  const [address, setAddress] = useState('');
  const [hubs, setHubs] = useState([]);
  const [selected, setSelected] = useState(context?.storeId ?? '');
  const [channel, setChannel] = useState(context?.channel ?? 'lo');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [links, setLinks] = useState({});
  const calculationContext = value ? { storeId: value.storeId, channel: value.channel } : context;
  const missingItems = (value?.items ?? []).filter((item) => item.rub == null);

  async function findHubs(event) {
    event.preventDefault();
    setPending(true);
    setError('');
    setHubs([]);
    setSelected('');
    try {
      const { hubs: results } = await send(address.trim());
      setHubs(results);
      if (results.length === 1) setSelected(results[0].id);
      if (!results.length) setError('Магазины не найдены.');
    } catch (failure) {
      setError(failure.message);
    } finally {
      setPending(false);
    }
  }

  return <section className="portion-price">
    <h2>Цена порции по Ленте</h2>
    {value?.rub != null && <p><strong>{value.rub.toLocaleString('ru-RU')} ₽</strong> · {value.date}{value.missing.length ? ' · частичная оценка' : ''}</p>}
    {value?.rub === null && <p>Цену порции оценить не удалось.</p>}
    {!!value?.missing.length && !missingItems.length && <p>Без цены: {value.missing.join(', ')}.</p>}
    {missingItems.length > 0 && <div>
      <h3>Что не вошло в оценку</h3>
      <ul>{missingItems.map((item) => (
        <li key={item.index}>
          <strong>{item.name}</strong> — {reasons[item.reason] ?? 'Цена не определена'}.
          {item.product && <div>По ссылке: {item.product}</div>}
          <form className="plan-actions" onSubmit={(event) => {
            event.preventDefault();
            const link = (links[item.index] ?? item.link ?? '').trim();
            if (link) onEstimate(calculationContext, { index: item.index, link });
          }}>
            <input type="url" aria-label={`Ссылка Ленты для ${item.name}`} placeholder="https://lenta.com/product/…"
              value={links[item.index] ?? item.link ?? ''} maxLength={1500} disabled={disabled || pending}
              onChange={(event) => setLinks({ ...links, [item.index]: event.target.value })} />
            <button disabled={disabled || pending || !(links[item.index] ?? item.link ?? '').trim()}>Использовать товар</button>
          </form>
        </li>
      ))}</ul>
    </div>}
    {(value?.items ?? []).some((item) => item.rub != null) && <details>
      <summary>Расчёт по ингредиентам</summary>
      <ul>{value.items.filter((item) => item.rub != null).map((item) => (
        <li key={item.index}>{item.name} — {item.rub.toLocaleString('ru-RU')} ₽{item.product ? ` · ${item.product}` : ''}</li>
      ))}</ul>
    </details>}
    <details open={!context || undefined}>
      <summary>{context ? `Магазин Ленты №${context.storeId}` : 'Выбрать магазин Ленты'}</summary>
      <form className="plan-actions" onSubmit={findHubs}>
        <input aria-label="Адрес для поиска Ленты" value={address} maxLength={180}
          placeholder="Город, улица, дом" disabled={disabled || pending}
          onChange={(event) => { setAddress(event.target.value); setHubs([]); setSelected(''); }} />
        <button disabled={disabled || pending || address.trim().length < 3}>Найти магазины</button>
      </form>
      <div className="plan-actions">
        {hubs.length > 0 && <label>Магазин <select value={selected} disabled={disabled || pending} onChange={(event) => setSelected(Number(event.target.value) || '')}>
          <option value="">Выберите магазин</option>
          {hubs.map((hub) => <option key={hub.id} value={hub.id}>{hub.address}</option>)}
        </select></label>}
        {(selected || hubs.length > 0) && <label>Получение <select value={channel} disabled={disabled || pending} onChange={(event) => setChannel(event.target.value)}>
          <option value="lo">Доставка</option><option value="locc">Самовывоз</option>
        </select></label>}
        <button type="button" disabled={!selected || disabled || pending}
          onClick={() => onEstimate({ storeId: selected, channel })}>Рассчитать цену</button>
      </div>
    </details>
    {pending && <p role="status">Ищем магазины…</p>}
    {error && <p role="alert" className="error">{error}</p>}
  </section>;
}
