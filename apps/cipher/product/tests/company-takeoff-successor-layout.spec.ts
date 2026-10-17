import { test, expect } from '@playwright/test';
import { mockSuccessor, openSuccessor } from './company-takeoff-successor-fixture';
import { unit } from './company-takeoff-fixture';

test('long canonical unit and nested manual controls stay within phone card content', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const f = await mockSuccessor(page, { sameSource: true });
  const symbol = 'RC01cc066dc8ba8';
  for (const r of [f.before, f.after]) for (const u of r.unit_manifest.records) if (u.kind === 'uom') u.fields.symbol = symbol;
  await page.route('**/api/method/cipher_aec.estimating.company_api.list_units*', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: { schema: 'cipher.api.v1', data: { items: [{ ...unit, fields: { ...unit.fields, symbol } }] } } }) }));
  await openSuccessor(page, false, 1);
  const card = page.getByRole('region', { name: 'Author manual measurement successor', exact: true }).getByRole('region', { name: 'Company drawing source', exact: true });
  await card.getByRole('combobox', { name: 'Manual quantity unit', exact: true }).click();
  await page.getByRole('option', { name: `${symbol} · area · 2 decimal places`, exact: true }).click();
  await card.getByRole('textbox', { name: 'Manual quantity', exact: true }).fill('18.00');
  await card.getByRole('textbox', { name: 'Drawing locator', exact: true }).fill('Explicit revised manual quantity');
  await card.getByRole('textbox', { name: 'Manual quantity reason', exact: true }).fill('Review each replacement input without changing the original.');
  const reviewed = card.getByRole('checkbox', { name: 'I reviewed the original measurement and the replacement source, quantity and unit', exact: true });
  await reviewed.focus(); await reviewed.press('Space'); await expect(reviewed).toBeChecked();
  const overflow = await card.evaluate(el => {
    const box = el.getBoundingClientRect(), style = getComputedStyle(el);
    const left = box.left + parseFloat(style.paddingLeft), right = box.right - parseFloat(style.paddingRight);
    return [...el.querySelectorAll('section,p,ui5-title,ui5-select,ui5-input,ui5-textarea,ui5-checkbox,ui5-button')].filter(child => !child.closest('.drawing-scroll,.drawing-toolbar') && child.getBoundingClientRect().width > 0).flatMap(child => {
      const r = child.getBoundingClientRect();
      return r.left < left - 1 || r.right > right + 1 || child instanceof HTMLElement && child.tagName === 'P' && child.scrollWidth > child.clientWidth + 1 ? [{ tag: child.tagName, left: r.left, right: r.right, cardRight: right }] : [];
    });
  });
  expect(overflow).toEqual([]);
  expect(f.writes).toEqual([]);
});
