const money = n => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' });

export function selectedLayout(layout, selectedIds, budget) {
  const elements = layout.elements.filter(e => selectedIds.has(e.id));
  const materials = elements.reduce((sum, e) => sum + (e.sourced_product ? e.sourced_product.price * e.quantity : 0), 0);
  const min = elements.reduce((sum, e) => sum + (e.estimated_feature?.cost_range_usd.min || 0), 0);
  const max = elements.reduce((sum, e) => sum + (e.estimated_feature?.cost_range_usd.max || 0), 0);
  const complete = elements.every(e => e.sourced_product || e.estimated_feature);
  const total = { min: Math.round((materials + min)*100)/100, max: Math.round((materials + max)*100)/100 };
  let note = total.min > budget ? `Over budget by ${money(total.min-budget)}–${money(total.max-budget)}.`
    : total.max > budget ? `May exceed budget by up to ${money(total.max-budget)}.` : 'Within budget for the selected items.';
  if (!complete) {
    if (total.max <= budget) note = 'Known costs are within budget.';
    note += ' Partial total: selected unpriced items are excluded.';
  }
  return { ...layout, elements, sourced_materials_total_usd: Math.round(materials*100)/100,
    estimated_features_range_usd: { min, max }, project_total_range_usd: total,
    sourcing_complete: complete, budget, budget_note: note };
}
