import { test, expect } from '@playwright/test';

/**
 * SYS-176: Drag-and-drop status changes between board columns.
 *
 * Verifies:
 * 1. Dragging a card from "todo" to "in_progress" updates its status in the DB.
 * 2. After a page reload the card stays in the destination column (persistence).
 */

test.describe('Drag-and-drop — cross-column status changes', () => {
  test('drag card from Todo to In Progress → persists after reload', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(
      page.getByRole('heading', { name: /tracker/i }),
    ).toBeVisible();

    // Create a test ticket via the keyboard shortcut → CreateModal.
    await page.keyboard.press('c');
    const titleInput = page.getByLabel(/title/i);
    await expect(titleInput).toBeVisible();
    await titleInput.fill('dnd test ticket');
    await page.getByLabel(/description/i).fill('drag me');
    await page.getByRole('button', { name: /^Create$/ }).click();

    // Card appears in the Todo column.
    const card = page.getByText('dnd test ticket').first();
    await expect(card).toBeVisible({ timeout: 5000 });

    // Locate the Todo and In Progress column headers to bound the drag.
    const todoColumn = page.locator('section').filter({ has: page.getByText('Todo', { exact: true }) }).first();
    const inProgressColumn = page
      .locator('section')
      .filter({ has: page.getByText('In progress', { exact: true }) })
      .first();

    // Find the card button inside the Todo column.
    const cardButton = todoColumn.getByRole('button', {
      name: /dnd test ticket/i,
    });
    await expect(cardButton).toBeVisible({ timeout: 3000 });

    // Get bounding boxes for source card and destination column.
    const cardBox = await cardButton.boundingBox();
    const destBox = await inProgressColumn.boundingBox();
    if (!cardBox || !destBox) throw new Error('Could not get bounding boxes for drag');

    // Perform the drag: start in the middle of the card, move to the center of
    // the In Progress column, then release. We use dispatchEvent to avoid
    // Playwright's built-in drag (which uses HTML5 DnD rather than Pointer events).
    const srcX = cardBox.x + cardBox.width / 2;
    const srcY = cardBox.y + cardBox.height / 2;
    const destX = destBox.x + destBox.width / 2;
    const destY = destBox.y + destBox.height / 2;

    await page.mouse.move(srcX, srcY);
    await page.mouse.down();
    // Move in small increments so the PointerSensor's distance threshold is exceeded.
    await page.mouse.move(srcX + 10, srcY, { steps: 3 });
    await page.mouse.move(destX, destY, { steps: 20 });
    await page.mouse.up();

    // The optimistic update should move the card immediately; wait for it to
    // appear in the In Progress column before reloading.
    const inProgressCard = inProgressColumn.getByRole('button', {
      name: /dnd test ticket/i,
    });
    await expect(inProgressCard).toBeVisible({ timeout: 5000 });

    // Confirm the card is no longer in the Todo column.
    await expect(
      todoColumn.getByRole('button', { name: /dnd test ticket/i }),
    ).not.toBeVisible({ timeout: 3000 });

    // Reload the page — the status must persist in the DB.
    await page.reload();
    await expect(
      page.getByRole('heading', { name: /tracker/i }),
    ).toBeVisible();

    // Re-locate columns after reload.
    const inProgressAfterReload = page
      .locator('section')
      .filter({ has: page.getByText('In progress', { exact: true }) })
      .first();

    const persistedCard = inProgressAfterReload.getByRole('button', {
      name: /dnd test ticket/i,
    });
    await expect(persistedCard).toBeVisible({ timeout: 5000 });
  });
});
