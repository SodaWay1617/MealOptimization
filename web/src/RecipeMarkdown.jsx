import React from 'react';
import Markdown from 'react-markdown';

const EMBED = /!?\[\[!?([^\[\]|\r\n]+?\.(?:png|jpe?g|gif|webp|avif|bmp))(?:\|([^\]\r\n]*))?\]\]/gi;

export function imageUrl(recipeId, ref) {
  return '/api/recipe/image?' + new URLSearchParams({ id: recipeId, ref: ref.trim() });
}

function obsidianImages(recipeId) {
  function transform(node) {
    if (!node.children || node.type === 'link') return;
    node.children = node.children.flatMap((child) => {
      if (child.type !== 'text') {
        transform(child);
        return [child];
      }
      const nodes = [];
      let position = 0;
      for (const match of child.value.matchAll(EMBED)) {
        if (match.index > position) nodes.push({ type: 'text', value: child.value.slice(position, match.index) });
        nodes.push({ type: 'image', alt: 'Фото рецепта', url: imageUrl(recipeId, match[1]) });
        position = match.index + match[0].length;
      }
      if (position === 0) return [child];
      if (position < child.value.length) nodes.push({ type: 'text', value: child.value.slice(position) });
      return nodes;
    });
  }
  return () => transform;
}

function RecipeImage({ src, alt }) {
  return <img src={src} alt={alt} loading="lazy" decoding="async" />;
}

export function RecipeMarkdown({ recipe }) {
  return (
    <Markdown remarkPlugins={[obsidianImages(recipe.id)]} components={{ img: RecipeImage }}>
      {recipe.body}
    </Markdown>
  );
}

export function RecipeCover({ recipe }) {
  const image = Array.from(recipe.body.matchAll(EMBED))[0];
  return image ? <RecipeImage src={imageUrl(recipe.id, image[1])} alt={recipe.title} /> : null;
}
