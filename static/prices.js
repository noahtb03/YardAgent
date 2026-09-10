export function showPrices(data, state) {
const money = value => Number(value).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
        document.querySelector('#materials-total').textContent =
          `Sourced materials${data.sourcing_complete ? '' : ' (partial)'}: ${money(data.sourced_materials_total_usd)}`;
        const range = data.estimated_features_range_usd;
        document.querySelector('#features-total').textContent =
          `Estimated features: ${money(range.min)}–${money(range.max)}`;
        const total = data.project_total_range_usd;
        document.querySelector('#project-total').textContent = total
          ? `Total${data.sourcing_complete ? '' : ' (partial)'}: ${money(total.min)}–${money(total.max)} • Budget: ${money(data.budget || state.budget)}` : '';
        document.querySelector('#budget-note').textContent = data.budget_note || '';
        const items = document.querySelector('#sourced-items');
        items.replaceChildren();
        for (const element of data.elements) {
          const item = document.createElement('li');
          item.textContent = `${element.type} × ${element.quantity}: `;
          if (element.sourced_product) {
            const product = element.sourced_product;
            const link = document.createElement('a');
            link.href = product.url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = product.name;
            item.append(link, ` — ${product.retailer || 'Home Depot'}: ${money(product.price)} per retail unit; ${money(element.sourced_total_usd)} total (lowest confirmed match)`);
            if (element.alternative_products?.length) {
              const details = document.createElement('details');
              const summary = document.createElement('summary');
              summary.textContent = `See ${element.alternative_products.length} alternatives`;
              const alternatives = document.createElement('ul');
              for (const alternative of element.alternative_products) {
                const row = document.createElement('li');
                const alternativeLink = document.createElement('a');
                alternativeLink.href = alternative.url;
                alternativeLink.target = '_blank';
                alternativeLink.rel = 'noopener noreferrer';
                alternativeLink.textContent = alternative.name;
                row.append(alternativeLink, ` — ${alternative.retailer}: ${money(alternative.price)} per retail unit`);
                alternatives.append(row);
              }
              details.append(summary, alternatives);
              item.append(details);
            }
          } else if (element.estimated_feature) {
            const estimate = element.estimated_feature;
            item.append(`Estimated ${money(estimate.cost_range_usd.min)}–${money(estimate.cost_range_usd.max)} (${estimate.basis}; U.S. national). `);
            const link = document.createElement('a');
            link.href = estimate.source_url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = 'Cost reference';
            if (estimate.source_url) item.append(link);
          } else {
            item.append(`Not sourced: ${element.sourcing_note} Excluded from the materials total.`);
          }
          items.append(item);
        }

document.querySelector('#source-totals').hidden = false;
}
