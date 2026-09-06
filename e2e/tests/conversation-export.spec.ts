import { test, expect } from '@playwright/test'

test.describe('Conversation export', () => {
  test.beforeEach(async ({ page, context }) => {
    // Stub window.print on every page/popup in this context — the real
    // system print dialog would hang a headless run. printConversationAsPdf
    // (client/src/utils/conversationExport.ts) calls it on the popup window
    // it opens, right after writing the HTML, so this must be registered
    // before that popup's document loads.
    await context.addInitScript(() => {
      // @ts-expect-error test-only stub
      window.print = () => { window.__printed = true }
    })

    await page.goto('/')
    await expect(page.locator('textarea[name="input"]')).toBeVisible({ timeout: 15_000 })

    await page.fill('textarea[name="input"]', 'What is metastasis?')
    await page.keyboard.press('Enter')
    const assistantBubble = page.locator('.message-bubble-assistant').last()
    await expect(async () => {
      const text = await assistantBubble.textContent()
      expect(text?.trim().length).toBeGreaterThan(20)
    }).toPass({ timeout: 90_000 })
  })

  test('downloads the conversation as Markdown, including a Sources section', async ({ page }) => {
    await page.getByRole('button', { name: 'Export conversation' }).click()

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('menuitem', { name: 'Download as Markdown' }).click(),
    ])

    expect(download.suggestedFilename()).toMatch(/\.md$/)
    const stream = await download.createReadStream()
    const chunks: Buffer[] = []
    for await (const chunk of stream!) chunks.push(chunk as Buffer)
    const content = Buffer.concat(chunks).toString('utf-8')

    expect(content).toContain('**You**')
    expect(content).toContain('metastasis')
    expect(content).toContain('**CancerBot**')
    // The default context's assistant answers cite real sources — the
    // export must surface them as a dedicated, linked section.
    expect(content).toContain('## Sources')
    expect(content).toMatch(/\[.+\]\(https?:\/\/.+\)/)
  })

  test('opens a print-ready window for PDF export, including sources', async ({ page }) => {
    await page.getByRole('button', { name: 'Export conversation' }).click()

    const [popup] = await Promise.all([
      page.waitForEvent('popup'),
      page.getByRole('menuitem', { name: 'Download as PDF' }).click(),
    ])
    await popup.waitForLoadState('domcontentloaded')

    const printed = await popup.evaluate(() => (window as unknown as { __printed?: boolean }).__printed)
    expect(printed).toBe(true)

    const bodyText = await popup.textContent('body')
    expect(bodyText).toContain('metastasis')
    expect(bodyText).toContain('Sources')

    await expect(popup.locator('.header img[alt="CancerBot"]')).toHaveAttribute(
      'src',
      'https://cancer-bot.com/cancerbot_light.png',
    )

    // The assistant's answer cites sources inline (e.g. [doi:...]) — those
    // must be real clickable links in the exported PDF, not just the
    // separate Sources list at the end.
    const inlineCitationLink = popup.locator('.message.assistant .content a').first()
    await expect(inlineCitationLink).toBeVisible()
    const href = await inlineCitationLink.getAttribute('href')
    expect(href).toMatch(/^https?:\/\//)
  })
})
