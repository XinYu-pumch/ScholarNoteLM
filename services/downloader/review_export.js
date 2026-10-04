(() => {
  'use strict';
  const db = JSON.parse(document.getElementById('reference-data').textContent);
  const body = document.body;
  const main = document.getElementById('main');
  const toc = document.getElementById('toc');
  const ref = document.getElementById('ref');
  const scrim = document.getElementById('scrim');
  const mobile = matchMedia('(max-width: 799px)');
  const overlayRef = matchMedia('(max-width: 1199px)');
  const items = [...document.querySelectorAll('.toc-item')];
  const sections = [...document.querySelectorAll('.sec')];
  const collapsed = new Set();
  let citation = null;
  let returnFocus = null;
  let drawer = null;

  function syncPanels() {
    toc.hidden = !body.classList.contains('toc-open');
    ref.hidden = !body.classList.contains('ref-open');
    document.getElementById('toggle-toc').setAttribute('aria-expanded', String(!toc.hidden));
    document.getElementById('toggle-ref').setAttribute('aria-expanded', String(!ref.hidden));
    drawer = !ref.hidden && overlayRef.matches ? ref : !toc.hidden && mobile.matches ? toc : null;
    scrim.hidden = !drawer;
    main.inert = !!drawer;
    toc.inert = !!drawer && drawer !== toc;
    ref.inert = !!drawer && drawer !== ref;
    for (const panel of [toc, ref]) {
      if (panel === drawer) { panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true'); }
      else { panel.removeAttribute('role'); panel.removeAttribute('aria-modal'); }
    }
  }
  function setPanel(name, open, focus = true) {
    if (open) {
      returnFocus = document.activeElement;
      if (mobile.matches) body.classList.remove(name === 'toc' ? 'ref-open' : 'toc-open');
    }
    body.classList.toggle(name + '-open', open);
    syncPanels();
    if (focus && open && drawer) drawer.querySelector('.panel-close').focus();
    if (focus && !open) {
      const target = returnFocus && !returnFocus.closest('[hidden]') && !returnFocus.closest('[inert]') ? returnFocus : document.getElementById('toggle-' + name);
      target.focus({preventScroll: true});
    }
  }
  if (mobile.matches) body.classList.remove('toc-open');
  syncPanels();
  for (const name of ['toc', 'ref']) {
    document.getElementById('toggle-' + name).addEventListener('click', () => setPanel(name, !body.classList.contains(name + '-open')));
  }
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => setPanel(button.dataset.close, false)));
  scrim.addEventListener('click', () => { if (drawer) setPanel(drawer.id, false); });
  document.getElementById('print').addEventListener('click', () => window.print());
  function resized() {
    if (mobile.matches && body.classList.contains('ref-open')) body.classList.remove('toc-open');
    syncPanels();
    if (drawer && !drawer.contains(document.activeElement)) drawer.querySelector('.panel-close').focus();
    updateProgress();
  }
  mobile.addEventListener('change', resized);
  overlayRef.addEventListener('change', resized);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      if (drawer) setPanel(drawer.id, false);
      else if (!ref.hidden) setPanel('ref', false);
    }
    if (event.key === 'Tab' && drawer) {
      const focusable = [...drawer.querySelectorAll('button, a[href]')].filter(el => el.getClientRects().length);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || !drawer.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !drawer.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    }
  });

  function renderToc() {
    for (const item of items) {
      const serial = item.dataset.serial;
      item.hidden = [...collapsed].some(parent => serial.startsWith(parent + '.'));
      const toggle = item.querySelector('button');
      if (toggle) {
        toggle.setAttribute('aria-expanded', String(!collapsed.has(serial)));
        toggle.setAttribute('aria-label', (collapsed.has(serial) ? '展开 ' : '折叠 ') + serial);
      }
    }
  }
  for (const item of items) {
    const toggle = item.querySelector('button');
    if (toggle) toggle.addEventListener('click', () => {
      const serial = item.dataset.serial;
      if (collapsed.has(serial)) collapsed.delete(serial); else collapsed.add(serial);
      renderToc();
    });
    item.querySelector('a').addEventListener('click', () => {
      if (mobile.matches) { setPanel('toc', false, false); main.focus({preventScroll: true}); }
    });
  }

  function show(button) {
    const {pmid, scope} = button.dataset;
    const area = document.getElementById('area');
    area.replaceChildren();
    if (citation) citation.setAttribute('aria-pressed', 'false');
    citation = button;
    button.setAttribute('aria-pressed', 'true');
    const entries = (db[scope] || {})[pmid] || [];
    const summary = document.createElement('div'); summary.className = 'source-summary';
    const title = document.createElement('strong'); title.textContent = 'PMID ' + pmid;
    summary.append(title, document.createTextNode('章节 ' + scope + ' · ' + entries.length + ' 段引用素材'));
    area.append(summary);
    entries.forEach((entry, index) => {
      const card = document.createElement('div'); card.className = 'card';
      const heading = document.createElement('div'); heading.className = 'ct';
      heading.textContent = '素材 ' + String(index + 1).padStart(2, '0') + ' · PMID: ' + pmid + '（来源章节：' + scope + '）';
      const content = document.createElement('div'); content.className = 'cb';
      if (typeof entry === 'object' && entry !== null) {
        // HTML is produced only by the exporter's escaping/allowlist renderer.
        content.classList.add('structured'); content.innerHTML = entry.html;
        for (const resource of entry.resources || []) {
          const details = document.createElement('details'); details.className = 'source-resource';
          const label = document.createElement('summary');
          label.textContent = (resource.kind === 'table' ? '完整原文表格' : '关联图片') + ' · 行 ' + resource.lineStart + '–' + resource.lineEnd;
          details.append(label);
          const material = document.createElement('div'); material.className = 'source-resource-content';
          if (resource.kind === 'table') material.innerHTML = resource.html;
          else if (/^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$/.test(resource.dataUrl || '')) {
            const img = document.createElement('img'); img.src = resource.dataUrl; img.alt = 'PMID ' + resource.pmid + ' 的关联图片'; material.append(img);
          } else material.textContent = resource.error || '图片快照不可用';
          details.append(material);
          for (const context of resource.context || []) {
            const nearby = document.createElement('details'); const title = document.createElement('summary');
            title.textContent = context.position === 'before' ? '资源之前的原文' : '资源之后的原文';
            const paragraph = document.createElement('div'); paragraph.innerHTML = context.html;
            nearby.append(title, paragraph); details.append(nearby);
          }
          content.append(details);
        }
        card.append(heading, content); area.append(card); return;
      }
      const text = String(entry);
      // Source snippets may contain scientific superscripts/subscripts. Render only
      // these two attribute-free tags; all other source markup remains inert text.
      let cursor = 0;
      for (const match of text.matchAll(/<(sup|sub)>([^<>]*)<\/\1>/gi)) {
        content.append(document.createTextNode(text.slice(cursor, match.index)));
        const script = document.createElement(match[1].toLowerCase()); script.textContent = match[2];
        content.append(script); cursor = match.index + match[0].length;
      }
      content.append(document.createTextNode(text.slice(cursor)));
      card.append(heading, content); area.append(card);
    });
    if (!entries.length) {
      const tip = document.createElement('p'); tip.className = 'tip'; tip.textContent = '当前小节未找到该 PMID 的素材。'; area.append(tip);
    }
    const link = document.createElement('a'); link.href = 'https://pubmed.ncbi.nlm.nih.gov/' + pmid + '/';
    link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = '前往 PubMed · ' + pmid + ' ↗'; area.append(link);
    setPanel('ref', true);
    area.scrollTop = 0;
    // Opening the desktop column changes line wrapping; keep the citation in view.
    if (!overlayRef.matches) button.scrollIntoView({block: 'nearest', behavior: 'instant'});
  }
  document.querySelectorAll('.lnk').forEach(button => {
    button.setAttribute('aria-label', '查看 PMID ' + button.dataset.pmid + ' 的引用素材');
    button.setAttribute('aria-controls', 'ref');
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => show(button));
  });
  let currentId = '';
  function updateProgress() {
    const total = main.scrollHeight - main.clientHeight;
    const percentage = total > 0 ? Math.min(100, Math.round(main.scrollTop / total * 100)) : 100;
    document.getElementById('progress').style.width = percentage + '%';
    document.getElementById('progress-label').textContent = percentage + '%';
    const top = main.getBoundingClientRect().top;
    let current = sections[0];
    for (const section of sections) {
      if (section.getBoundingClientRect().top > top + 100) break;
      current = section;
    }
    if (!current || current.id === currentId) return;
    currentId = current.id;
    for (const item of items) {
      const link = item.querySelector('a');
      if (link.hash === '#' + currentId) {
        link.setAttribute('aria-current', 'location');
        // Keep the current heading visible even after a collapsed branch is entered.
        for (const parent of collapsed) if (item.dataset.serial.startsWith(parent + '.')) collapsed.delete(parent);
        renderToc();
        const list = document.querySelector('.toc-list');
        if (!toc.hidden) {
          const box = item.getBoundingClientRect(), bounds = list.getBoundingClientRect();
          if (box.top < bounds.top || box.bottom > bounds.bottom) list.scrollTop += box.top - bounds.top - 32;
        }
      } else link.removeAttribute('aria-current');
    }
  }
  let pending = false;
  main.addEventListener('scroll', () => {
    if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; updateProgress(); }); }
  }, {passive: true});
  new ResizeObserver(updateProgress).observe(main);
  updateProgress();
})();
