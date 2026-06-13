import { test, expect } from '@playwright/test';

/**
 * SYS-178: Markdown rendering in descriptions, activity comments.
 *
 * Verifies:
 * 1. Markdown syntax in a ticket description renders as HTML (not raw `#`/`*`)
 * 2. Code blocks use a <pre><code> structure (JetBrains Mono)
 * 3. Links render as <a> elements
 * 4. Raw HTML in a description is escaped (no XSS path)
 * 5. Comments posted via the CommentThread form render as markdown in ActivityTimeline
 */

const MARKDOWN_DESCRIPTION = `# Main heading

A paragraph with **bold** and _italic_ text.

- Item one
- Item two with \`inline code\`

\`\`\`
const x = 42;
\`\`\`

[Visit example](https://example.com)`;

const RAW_HTML_DESCRIPTION = `<script>window.__xss = true;</script>

<b>should be escaped</b>`;

test.describe('Markdown rendering — descriptions', () => {
  test('markdown description renders as formatted HTML', async ({ page }) => {
    await page.goto('/');

    // Create a ticket with a markdown description
    await page.keyboard.press('c');
    await page.getByLabel(/title/i).fill('Markdown test ticket');
    await page.getByLabel(/description/i).fill(MARKDOWN_DESCRIPTION);
    await page.getByRole('button', { name: /^Create$/ }).click();

    // Open the modal
    const cardText = page.getByText('Markdown test ticket').first();
    await expect(cardText).toBeVisible({ timeout: 5000 });
    await cardText.click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    // h1 renders — "Main heading" should appear as an <h1> not as "# Main heading"
    const heading = dialog.getByRole('heading', { name: 'Main heading' });
    await expect(heading).toBeVisible();

    // Paragraph text renders
    await expect(dialog.getByText(/A paragraph with/)).toBeVisible();

    // Bold renders as <strong>
    const bold = dialog.locator('strong', { hasText: 'bold' });
    await expect(bold).toBeVisible();

    // List items render as <li>
    await expect(dialog.locator('li', { hasText: 'Item one' })).toBeVisible();

    // Inline code renders
    const inlineCode = dialog.locator('code', { hasText: 'inline code' });
    await expect(inlineCode).toBeVisible();

    // Code block renders inside <pre>
    const codeBlock = dialog.locator('pre code', { hasText: 'const x = 42' });
    await expect(codeBlock).toBeVisible();

    // Link renders as <a>
    const link = dialog.locator('a', { hasText: 'Visit example' });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', 'https://example.com');

    // Raw "#" character should NOT be visible (it was consumed by markdown parser)
    await expect(dialog.getByText('# Main heading')).not.toBeVisible();

    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible({ timeout: 3000 });
  });

  test('raw HTML in description is escaped (no XSS)', async ({ page }) => {
    await page.goto('/');

    // Create ticket with raw HTML content
    await page.keyboard.press('c');
    await page.getByLabel(/title/i).fill('XSS escape test');
    await page.getByLabel(/description/i).fill(RAW_HTML_DESCRIPTION);
    await page.getByRole('button', { name: /^Create$/ }).click();

    const cardText = page.getByText('XSS escape test').first();
    await expect(cardText).toBeVisible({ timeout: 5000 });
    await cardText.click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    // The <script> tag must NOT have been executed
    const xssFlag = await page.evaluate(() => (window as unknown as Record<string, unknown>).__xss);
    expect(xssFlag).toBeUndefined();

    // The <script> tag should not appear as a live <script> element in the description area
    const scriptTags = await dialog.locator('script').count();
    expect(scriptTags).toBe(0);

    await page.keyboard.press('Escape');
  });
});

test.describe('Markdown rendering — activity comments', () => {
  test('markdown comment renders in ActivityTimeline', async ({ page }) => {
    await page.goto('/');

    // Create a plain ticket
    await page.keyboard.press('c');
    await page.getByLabel(/title/i).fill('Comment markdown test');
    await page.getByLabel(/description/i).fill('Plain description');
    await page.getByRole('button', { name: /^Create$/ }).click();

    const cardText = page.getByText('Comment markdown test').first();
    await expect(cardText).toBeVisible({ timeout: 5000 });
    await cardText.click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    // Post a markdown comment
    const commentInput = dialog.getByPlaceholder(/add a comment/i);
    await commentInput.fill('**Important:** see `config.ts` for details');
    await dialog.getByRole('button', { name: /^Post$/ }).click();

    // ActivityTimeline should update and show the comment as markdown
    // Bold "Important:" should render as <strong>
    const boldText = dialog.locator('strong', { hasText: 'Important:' });
    await expect(boldText).toBeVisible({ timeout: 5000 });

    // Inline code should render
    const codeText = dialog.locator('code', { hasText: 'config.ts' });
    await expect(codeText).toBeVisible();

    // The raw "**" characters should not be visible
    await expect(dialog.getByText(/\*\*Important:/)).not.toBeVisible();

    await page.keyboard.press('Escape');
  });
});
