import { test, expect } from '@playwright/test';

/**
 * SYS-177: Inline card title editing without opening the modal.
 *
 * Verifies:
 * 1. Double-click on card title → inline input appears.
 * 2. Type a new title → Enter saves → title updates in card.
 * 3. After reload the new title persists (written to DB).
 * 4. Escape while editing reverts to the original title.
 * 5. Clicking the card normally (single-click) still opens the modal.
 * 6. Pencil icon appears on hover and triggers editing on click.
 */

test.describe('Inline title editing', () => {
  test('double-click → type → Enter → persists after reload', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /prism/i })).toBeVisible();

    // Create a ticket via keyboard shortcut.
    await page.keyboard.press('c');
    const titleInput = page.getByLabel(/title/i);
    await expect(titleInput).toBeVisible();
    await titleInput.fill('inline edit original title');
    await page.getByLabel(/description/i).fill('editing test');
    await page.getByRole('button', { name: /^Create$/ }).click();

    // Wait for card to appear in Todo column.
    const card = page.getByRole('button', { name: /inline edit original title/i }).first();
    await expect(card).toBeVisible({ timeout: 5000 });

    // Find the title span inside the card — double-click it.
    const titleSpan = card.locator('span', { hasText: 'inline edit original title' }).first();
    await titleSpan.dblclick();

    // Inline input should appear and be focused.
    const editInput = page.getByLabel(/edit title/i);
    await expect(editInput).toBeVisible({ timeout: 2000 });
    await expect(editInput).toBeFocused();

    // Clear and type the new title.
    await editInput.fill('inline edit renamed title');
    await editInput.press('Enter');

    // Input should be gone; card title should update optimistically.
    await expect(editInput).not.toBeVisible({ timeout: 3000 });
    await expect(page.getByRole('button', { name: /inline edit renamed title/i }).first()).toBeVisible({
      timeout: 5000,
    });

    // Reload — title must persist in DB.
    await page.reload();
    await expect(page.getByRole('heading', { name: /prism/i })).toBeVisible();
    await expect(
      page.getByRole('button', { name: /inline edit renamed title/i }).first(),
    ).toBeVisible({ timeout: 5000 });
  });

  test('Escape while editing reverts to original title', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /prism/i })).toBeVisible();

    // Create a ticket.
    await page.keyboard.press('c');
    const titleInput = page.getByLabel(/title/i);
    await expect(titleInput).toBeVisible();
    await titleInput.fill('escape reverts title');
    await page.getByLabel(/description/i).fill('esc test');
    await page.getByRole('button', { name: /^Create$/ }).click();

    const card = page.getByRole('button', { name: /escape reverts title/i }).first();
    await expect(card).toBeVisible({ timeout: 5000 });

    // Enter edit mode.
    const titleSpan = card.locator('span', { hasText: 'escape reverts title' }).first();
    await titleSpan.dblclick();

    const editInput = page.getByLabel(/edit title/i);
    await expect(editInput).toBeVisible({ timeout: 2000 });

    // Type a new value then press Escape.
    await editInput.fill('this should not be saved');
    await editInput.press('Escape');

    // Input gone; original title still shown.
    await expect(editInput).not.toBeVisible({ timeout: 2000 });
    await expect(page.getByRole('button', { name: /escape reverts title/i }).first()).toBeVisible({
      timeout: 3000,
    });
    await expect(page.getByText('this should not be saved')).not.toBeVisible();
  });

  test('single-click still opens modal when not editing', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /prism/i })).toBeVisible();

    // Create a ticket.
    await page.keyboard.press('c');
    const titleInput = page.getByLabel(/title/i);
    await expect(titleInput).toBeVisible();
    await titleInput.fill('modal still opens');
    await page.getByLabel(/description/i).fill('modal test');
    await page.getByRole('button', { name: /^Create$/ }).click();

    const card = page.getByRole('button', { name: /modal still opens/i }).first();
    await expect(card).toBeVisible({ timeout: 5000 });

    // Single-click on the card should open the modal.
    await card.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 3000 });
    await expect(dialog.getByRole('heading', { name: 'modal still opens' })).toBeVisible();

    // Close modal.
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible({ timeout: 3000 });
  });

  test('pencil icon click enters edit mode', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /prism/i })).toBeVisible();

    // Create a ticket.
    await page.keyboard.press('c');
    const titleInput = page.getByLabel(/title/i);
    await expect(titleInput).toBeVisible();
    await titleInput.fill('pencil edit test');
    await page.getByLabel(/description/i).fill('pencil test');
    await page.getByRole('button', { name: /^Create$/ }).click();

    const card = page.getByRole('button', { name: /pencil edit test/i }).first();
    await expect(card).toBeVisible({ timeout: 5000 });

    // Hover the card to reveal the pencil, then click it.
    await card.hover();
    const pencil = card.getByRole('button', { name: /edit title/i });
    await pencil.click();

    const editInput = page.getByLabel(/edit title/i);
    await expect(editInput).toBeVisible({ timeout: 2000 });
    await expect(editInput).toBeFocused();

    // Cancel with Escape.
    await editInput.press('Escape');
    await expect(editInput).not.toBeVisible({ timeout: 2000 });
  });
});
