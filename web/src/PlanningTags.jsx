import React from 'react';

export function PlanningTags({ labels, selected = [], onChange }) {
  return (
    <fieldset>
      <legend>Теги для плана питания</legend>
      <div className="tag-options">
        {Object.entries(labels).map(([value, label]) => (
          <label key={value}>
            <input type="checkbox" checked={selected.includes(value)}
              onChange={(event) => onChange(event.target.checked ? [...selected, value] : selected.filter((tag) => tag !== value))} />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
