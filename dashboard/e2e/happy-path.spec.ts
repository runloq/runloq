import { test, expect } from '@playwright/test';

/** Happy-path: open the dashboard → press `c` → fill form → see card →
 *  click card → edit description → see change. Exercises every layer
 *  the user touches in 10 seconds. */
test('create → see card → open modal → edit → close', async ({ page }) => {
  await page.goto('/');

  // Top bar renders even on an empty DB
  await expect(page.getByRole('heading', { name: /tracker/i })).toBeVisible();

  // c → CreateModal opens
  await page.keyboard.press('c');
  const titleInput = page.getByLabel(/title/i);
  await expect(titleInput).toBeVisible();

  await titleInput.fill('e2e smoke ticket');
  await page.getByLabel(/description/i).fill('written by playwright');
  await page.getByRole('button', { name: /^Create$/ }).click();

  // Card appears in the board
  const cardText = page.getByText('e2e smoke ticket').first();
  await expect(cardText).toBeVisible({ timeout: 5000 });

  // Click the card → modal opens with the title in DialogTitle
  await cardText.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('heading', { name: 'e2e smoke ticket' })).toBeVisible();

  // Edit
  await dialog.getByRole('button', { name: /edit/i }).click();
  const desc = page.getByLabel(/description/i);
  await desc.fill('updated by playwright');
  await page.getByRole('button', { name: /^Save$/ }).click();

  // Back to view mode showing the new description
  await expect(page.getByText('updated by playwright')).toBeVisible({ timeout: 5000 });

  // Esc closes the modal
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible({ timeout: 3000 });
});

test('search palette opens with "/" and finds the just-created ticket', async ({ page }) => {
  await page.goto('/');
  await page.keyboard.press('/');
  const search = page.getByPlaceholder(/search/i);
  await expect(search).toBeVisible();
  await search.fill('smoke');
  // Search needs ≥2 chars; the result should appear within 1s of FTS
  await expect(page.getByLabel('result').getByText(/e2e smoke ticket/i)).toBeVisible({
    timeout: 3000,
  });
  await page.keyboard.press('Escape');
});
