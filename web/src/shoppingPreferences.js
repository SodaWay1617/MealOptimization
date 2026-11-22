export const shops = [
  { id: 'vkusvill', name: 'ВкусВилл' },
  { id: 'lenta', name: 'Лента' },
];

export function readPreference(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem('meal-planner:' + key)) ?? fallback;
  } catch {
    return fallback;
  }
}

export function writePreference(key, value) {
  localStorage.setItem('meal-planner:' + key, JSON.stringify(value));
}

export function ingredientKey(name) {
  return name.toLocaleLowerCase('ru').trim().replace(/\s+/g, ' ');
}
