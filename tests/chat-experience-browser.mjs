import assert from 'node:assert/strict';
import {test} from 'node:test';
import {pathToFileURL} from 'node:url';
import {startChatFixture} from './fixtures/chat-experience-server.mjs';
const moduleUrl=process.env.RADHOUSE_PLAYWRIGHT_MODULE?pathToFileURL(process.env.RADHOUSE_PLAYWRIGHT_MODULE).href:new URL('../web/node_modules/@playwright/test/index.mjs',import.meta.url).href;
const {chromium,expect}=await import(moduleUrl);
await test('connected web chat searches, quotes and sends the exact OpenAI selection at desktop and phone sizes',async()=>{
  const fixture=await startChatFixture();
  let browser;
  try{
    browser=await chromium.launch({headless:true,...(process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH?{executablePath:process.env.RADHOUSE_CHROMIUM_EXECUTABLE_PATH}:{})});
    const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    fixture.turns[0].status='running';
    await page.goto(fixture.origin);await expect(page.locator('#inference-summary')).toHaveText('Default model');
    await expect(page.locator('[data-request-id="fixture-0"] time')).toHaveAttribute('datetime','2026-11-02T15:00:00.000Z');
    await page.getByRole('button',{name:'Find in conversation'}).click();
    await page.getByLabel('Search loaded messages').fill('useful next step');
    await expect(page.locator('.conversation-results button')).toHaveCount(1);
    await page.getByLabel('Search loaded messages').press('Tab');
    await expect(page.locator('.conversation-results button')).toBeFocused();
    const poll=page.waitForResponse(response=>response.url().endsWith('/chat/reply'));
    fixture.turns[11].output='## Start with one clear outcome\n\nA live update';
    await poll;
    await expect(page.locator('.conversation-results button')).toContainText('A live update');
    await expect(page.locator('.conversation-results button')).toBeFocused();
    await page.locator('.conversation-results button').click();
    await expect(page.locator('#conversation-finder')).toBeHidden();
    await expect(page.locator('[data-request-id="fixture-11"]')).toBeFocused();
    await page.locator('#message').fill('My draft');
    await page.getByRole('button',{name:'Quote in reply'}).last().click();
    await expect(page.locator('#message')).toHaveValue(/My draft\n\n> ## Start with one clear outcome/);
    await page.locator('#inference-summary').click();
    const model=page.getByLabel('Model',{exact:true}),thinking=page.getByLabel('Thinking',{exact:true});
    await model.selectOption(JSON.stringify(['custom:openai','gpt-6.1-sol']));
    await expect(thinking.locator('option[value="off"]')).toHaveCount(0);
    await expect(thinking.locator('option[value="ultra"]')).toHaveCount(0);
    await thinking.selectOption('max');
    await expect(page.getByText(/Conversation context is sent to OpenAI/)).toBeVisible();
    await model.selectOption(JSON.stringify(['custom:openai','gpt-6.1-terra']));await thinking.selectOption('off');
    await model.selectOption(JSON.stringify(['custom:openai','gpt-6-astra']));await thinking.selectOption('high');
    await model.press('Escape');await page.locator('#message').fill('A synthetic model test');await page.locator('#send').click();
    await expect(page.getByText('Synthetic receipt: your message and selected thinking arrived together.')).toBeVisible();
    assert.deepEqual(fixture.requests[0].inference,{provider:'custom:openai',model:'gpt-6-astra',thinking:'high'});
    for(const width of [390,320]){
      await page.setViewportSize({width,height:844});
      await expect(page.locator('#message')).toBeInViewport();
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      await page.locator('#inference-summary').click();await expect(model).toBeInViewport();await expect(thinking).toBeInViewport();await model.press('Escape');
      await page.getByRole('button',{name:'Find in conversation'}).click();
      await page.getByLabel('Search loaded messages').fill('<img onerror=alert(1)>');await expect(page.locator('.conversation-results button')).toHaveCount(0);
      await page.getByLabel('Search loaded messages').press('Escape');await expect(page.getByRole('button',{name:'Find in conversation'})).toBeFocused();
    }
    assert.deepEqual(errors,[]);
  }finally{try{await browser?.close();}finally{await fixture.close();}}
});
