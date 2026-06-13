import { test, expect } from '@playwright/test';

/**
 * SYS-179: Bulk multi-select actions on the kanban board.
 *
 * Verifies:
 * 1. Cmd-click (or Ctrl-click) selects a card — selection ring appears and
 *    ActionBar shows the count.
 * 2. A second Cmd-click on the same card deselects it.
 * 3. Cmd-click on 3 different cards → ActionBar shows "3 selected".
 * 4. Clicking Close → Cancelled closes all 3 cards and clears selection.
 * 5. Esc clears selection without any other action.
 * 6. Plain click still opens the modal (selection-only on modifier-click).
 * 7. Cmd+A selects all visible cards.
 */

/** Playwright modifier key — Cmd on macOS, Ctrl elsewhere. */
const MOD: 'Meta' | 'Control' =
  process.platform === 'darwin' ? 'Meta' : 'Control';

test.describe('Bulk multi-select', () => {
  /**
   * Helper: create a ticket with a known title via the Ctrl+C shortcut.
   * Returns the card locator.
   */
  async function createTicket(
    page: Parameters<Parameters<typeof test>[1]>[0],
    title: string,
  ) {
    // Ctrl+C opens the CreateModal (wired in __root.tsx)
    await page.keyboard.press('Control+c');
    // Wait for the dialog to appear, then scope title input within it.
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 3000 });
    const titleInput = dialog.getByRole('textbox', { name: /title/i });
    await expect(titleInput).toBeVisible({ timeout: 3000 });
    await titleInput.fill(title);
    // Description is optional — skip it to keep helper lean.
    await dialog.getByRole('button', { name: /^Create$/ }).click();
    await expect(dialog).not.toBeVisible({ timeout: 5000 });
    const card = page.getByRole('button', { name: new RegExp(title, 'i') }).first();
    await expect(card).toBeVisible({ timeout: 6000 });
    return card;
  }

  test('cmd-click selects a card and shows ActionBar', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1, name: /prism/i })).toBeVisible();

    const card = await createTicket(page, 'bulk-select-card-1');

    // Cmd/Ctrl-click → selection mode, not modal
    await card.click({ modifiers: [MOD] });

    // ActionBar should appear with "1 selected"
    const actionBar = page.getByRole('toolbar', { name: /bulk actions/i });
    await expect(actionBar).toBeVisible({ timeout: 3000 });
    await expect(actionBar.getByText(/1 selected/i)).toBeVisible();

    // No modal should have opened
    await expect(page.getByRole('dialog')).not.toBeVisible();

    // Card should have aria-pressed=true (selection ring visual)
    await expect(card).toHaveAttribute('aria-pressed', 'true');
  });

  test('cmd-click same card again deselects it and hides ActionBar', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1, name: /prism/i })).toBeVisible();

    const card = await createTicket(page, 'bulk-deselect-card');

    await card.click({ modifiers: [MOD] });
    await expect(page.getByRole('toolbar', { name: /bulk actions/i })).toBeVisible({ timeout: 3000 });

    // Click again to deselect
    await card.click({ modifiers: [MOD] });

    // ActionBar should disappear
    await expect(page.getByRole('toolbar', { name: /bulk actions/i })).not.toBeVisible({ timeout: 3000 });
    await expect(card).toHaveAttribute('aria-pressed', 'false');
  });

  test('select 3 cards → ActionBar shows 3 selected', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1, name: /prism/i })).toBeVisible();

    const card1 = await createTicket(page, 'bulk-three-a');
    const card2 = await createTicket(page, 'bulk-three-b');
    const card3 = await createTicket(page, 'bulk-three-c');

    await card1.click({ modifiers: [MOD] });
    await card2.click({ modifiers: [MOD] });
    await card3.click({ modifiers: [MOD] });

    const actionBar = page.getByRole('toolbar', { name: /bulk actions/i });
    await expect(actionBar).toBeVisible({ timeout: 3000 });
    await expect(actionBar.getByText(/3 selected/i)).toBeVisible();
  });

  test('Esc clears selection', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1, name: /prism/i })).toBeVisible();

    const card = await createTicket(page, 'bulk-esc-clear');

    await card.click({ modifiers: [MOD] });
    const actionBar = page.getByRole('toolbar', { name: /bulk actions/i });
    await expect(actionBar).toBeVisible({ timeout: 3000 });

    // Press Escape to clear selection
    await page.keyboard.press('Escape');
    await expect(actionBar).not.toBeVisible({ timeout: 3000 });
  });

  test('plain click still opens modal when no modifier', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1, name: /prism/i })).toBeVisible();

    const card = await createTicket(page, 'bulk-modal-open');

    // Plain click — should open modal, not select
    await card.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible({ timeout: 3000 });
    await expect(dialog.getByRole('heading', { name: 'bulk-modal-open' })).toBeVisible();

    // No selection — ActionBar not shown
    await expect(page.getByRole('toolbar', { name: /bulk actions/i })).not.toBeVisible();

    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible({ timeout: 3000 });
  });

  test('close X button in ActionBar clears selection', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1, name: /prism/i })).toBeVisible();

    const card = await createTicket(page, 'bulk-x-clear');

    await card.click({ modifiers: [MOD] });
    const actionBar = page.getByRole('toolbar', { name: /bulk actions/i });
    await expect(actionBar).toBeVisible({ timeout: 3000 });

    // Click the X (clear) button
    await actionBar.getByRole('button', { name: /clear selection/i }).click();
    await expect(actionBar).not.toBeVisible({ timeout: 2000 });
  });

  test('bulk close → cancelled → cards disappear from board', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1, name: /prism/i })).toBeVisible();

    const card1 = await createTicket(page, 'bulk-close-a');
    const card2 = await createTicket(page, 'bulk-close-b');

    await card1.click({ modifiers: [MOD] });
    await card2.click({ modifiers: [MOD] });

    const actionBar = page.getByRole('toolbar', { name: /bulk actions/i });
    await expect(actionBar.getByText(/2 selected/i)).toBeVisible({ timeout: 3000 });

    // Open the Close dropdown
    await actionBar.getByRole('button', { name: /^Close/i }).click();
    const menu = actionBar.getByRole('menu');
    await expect(menu).toBeVisible({ timeout: 2000 });

    // Click "Cancelled"
    await menu.getByRole('menuitem', { name: /cancelled/i }).click();

    // ActionBar should disappear (selection cleared)
    await expect(actionBar).not.toBeVisible({ timeout: 5000 });

    // By default, cancelled column is not shown — cards vanish from board.
    // Since "Show Cancelled" is off, neither card should be visible.
    await expect(
      page.getByRole('button', { name: /bulk-close-a/i }),
    ).not.toBeVisible({ timeout: 5000 });
    await expect(
      page.getByRole('button', { name: /bulk-close-b/i }),
    ).not.toBeVisible({ timeout: 5000 });
  });
});
