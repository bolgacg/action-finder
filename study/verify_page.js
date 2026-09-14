/* Render the page headless, capture any script error, screenshot it at desktop
   and phone width, probe for horizontal overflow, and walk every tour step.

   node study/verify_page.js [outdir] */
const { chromium } = require('/home/bolgac/projects/minimalist-workout-app/node_modules/playwright');
const path = require('path');
const fs = require('fs');

const PAGE = 'file://' + path.resolve(__dirname, '..', 'docs', 'index.html');
const OUT = process.argv[2] || path.resolve(__dirname, '..', 'data', 'shots');

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const errors = [];
  let fail = false;

  for (const [name, w, h] of [['desktop', 1536, 960], ['phone', 390, 844]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    page.on('pageerror', e => { errors.push(`[${name}] pageerror: ${e.message}`); });
    page.on('console', m => { if (m.type() === 'error') errors.push(`[${name}] console: ${m.text()}`); });
    await page.goto(PAGE + '?tour=off', { waitUntil: 'networkidle' });
    await page.waitForTimeout(600);

    const overflow = await page.evaluate(() => {
      const bad = [];
      const de = document.documentElement;
      if (de.scrollWidth > de.clientWidth + 1) {
        document.querySelectorAll('*').forEach(el => {
          const r = el.getBoundingClientRect();
          if (r.right > de.clientWidth + 1 && r.width > 0) {
            let ok = el;
            while (ok && ok !== document.body) {
              const st = getComputedStyle(ok);
              if (st.overflowX === 'auto' || st.overflowX === 'scroll') return;
              ok = ok.parentElement;
            }
            bad.push((el.tagName + (el.id ? '#' + el.id : '') + (el.className ? '.' + String(el.className).split(' ')[0] : '')) + ' right=' + Math.round(r.right));
          }
        });
      }
      return { scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, bad: bad.slice(0, 8) };
    });
    if (overflow.scrollWidth > overflow.clientWidth + 1) {
      console.log(`OVERFLOW at ${name}: scrollWidth ${overflow.scrollWidth} > ${overflow.clientWidth}`);
      overflow.bad.forEach(b => console.log('   ' + b));
      if (name === 'phone') fail = true;
    } else {
      console.log(`no horizontal overflow at ${name} (${w}px)`);
    }

    await page.screenshot({ path: path.join(OUT, `${name}-full.png`), fullPage: true });
    await page.screenshot({ path: path.join(OUT, `${name}-first.png`) });

    // Read back what the page actually printed, so the numbers can be checked.
    const printed = await page.evaluate(() => ({
      dek: document.querySelector('#dek') ? document.querySelector('#dek').innerText : null,
      verdicts: Array.from(document.querySelectorAll('.verdict')).map(v => v.innerText),
      stat: document.querySelector('#budgetstat') ? document.querySelector('#budgetstat').innerText.replace(/\n/g, ' | ') : null,
      queueRows: document.querySelectorAll('#queuetable tbody tr').length,
      indRows: document.querySelectorAll('#indtable tbody tr').length,
      exChips: document.querySelectorAll('#exchips .chip').length,
      cohort: document.querySelector('#cohorttext') ? document.querySelector('#cohorttext').innerText : null
    }));
    fs.writeFileSync(path.join(OUT, `${name}-printed.json`), JSON.stringify(printed, null, 1));
    if (name === 'desktop') {
      console.log('\nDEK: ' + (printed.dek || '(empty)'));
      printed.verdicts.forEach((v, i) => console.log(`VERDICT ${i + 1}: ${v}`));
      console.log('STAT: ' + printed.stat);
      console.log(`rows: queue ${printed.queueRows}, indicators ${printed.indRows}, example chips ${printed.exChips}`);
    }
    await ctx.close();
  }

  // Walk every tour step at both widths and confirm the highlight frames a real box.
  for (const [name, w, h] of [['desktop', 1536, 960], ['phone', 390, 844]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    page.on('pageerror', e => { errors.push(`[tour ${name}] pageerror: ${e.message}`); });
    await page.goto(PAGE, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1400);
    let step = 0;
    while (true) {
      const info = await page.evaluate(() => {
        const root = document.querySelector('#tour');
        if (!root || !root.classList.contains('on')) return null;
        const hl = document.querySelector('.tour-hl').getBoundingClientRect();
        const card = document.querySelector('.tour-card').getBoundingClientRect();
        const k = document.querySelector('.tour-card .tk');
        return {
          k: k ? k.textContent : '', hlTop: Math.round(hl.top), hlH: Math.round(hl.height),
          cardTop: Math.round(card.top), cardH: Math.round(card.height),
          overlaps: !(card.right < hl.left || card.left > hl.right || card.bottom < hl.top || card.top > hl.bottom)
        };
      });
      if (!info) break;
      step++;
      const bad = info.hlH < 40 || info.overlaps;
      if (bad) { fail = true; }
      console.log(`tour ${name} step ${step}: ${info.k} highlight top=${info.hlTop} h=${info.hlH} card top=${info.cardTop}${info.overlaps ? '  CARD COVERS THE HIGHLIGHT' : ''}${info.hlH < 40 ? '  HIGHLIGHT COLLAPSED' : ''}`);
      if (step === 1 && name === 'desktop') await page.screenshot({ path: path.join(OUT, 'tour-step1.png') });
      const next = await page.$('#tnext');
      if (!next) break;
      await next.click();
      await page.waitForTimeout(700);
      if (step > 12) break;
    }
    await ctx.close();
  }

  await browser.close();
  if (errors.length) {
    console.log('\nSCRIPT ERRORS:');
    errors.forEach(e => console.log('  ' + e));
    fail = true;
  } else {
    console.log('\nno script errors');
  }
  console.log('\nshots in ' + OUT);
  process.exit(fail ? 1 : 0);
})();
