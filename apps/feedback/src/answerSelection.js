export function toggleAnswer({ type, selected, option, maxChoices }) {
  if (type === "single") return [option];

  if (selected.includes(option)) {
    return selected.filter((answer) => answer !== option);
  }

  if (selected.length >= (maxChoices ?? Number.POSITIVE_INFINITY)) {
    return selected;
  }

  return [...selected, option];
}
