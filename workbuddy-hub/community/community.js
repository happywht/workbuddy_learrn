(() => {
  const listRoot = document.querySelector('#community-case-grid');
  const detailRoot = document.querySelector('#community-case-detail');
  if (!listRoot && !detailRoot) return;

  const escapeHtml = (value = '') => String(value)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');

  let cases = [];
  let activeFilter = 'all';
  let query = '';

  const normalizeDetail = item => item ? {
    ...(item.metadata || {}), ...item,
    version: item.current_version || item.version,
    inputs: item.inputs || item.metadata?.inputs || [],
    files: item.files || item.metadata?.files || [],
    steps: item.steps || item.metadata?.steps || [],
    checks: item.checks || item.metadata?.checks || [],
    prompt: item.prompt || item.metadata?.prompt || '',
    limitation: item.limitation || item.metadata?.limitation || '',
    learningPath: item.learningPath || item.metadata?.learningPath || '#'
  } : item;

  const caseCard = item => `<article class="community-case-card">
    <div class="case-card-top"><span>${escapeHtml(item.kind)}</span><strong>${escapeHtml(item.status)}</strong></div>
    <h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.summary)}</p>
    <div class="case-tags">${item.tags.map(tag => `<span>${escapeHtml(tag)}</span>`).join('')}</div>
    <dl><div><dt>适用</dt><dd>${escapeHtml(item.audience)}</dd></div><div><dt>目标产物</dt><dd>${escapeHtml(item.output)}</dd></div><div><dt>跟做用时</dt><dd>${escapeHtml(item.duration)}</dd></div></dl>
    <a class="case-card-link" href="case.html?id=${encodeURIComponent(item.id)}">查看案例 →</a>
  </article>`;

  const renderList = () => {
    const normalized = query.trim().toLowerCase();
    const visible = cases.filter(item => {
      const categoryMatch = activeFilter === 'all' || item.category === activeFilter;
      const text = [item.title, item.summary, item.audience, item.output, ...item.tags].join(' ').toLowerCase();
      return categoryMatch && (!normalized || text.includes(normalized));
    });
    listRoot.innerHTML = visible.length ? visible.map(caseCard).join('') : '<div class="community-empty">没有找到匹配案例，请换一个关键词或分类。</div>';
  };

  const renderDetail = item => {
    if (!item) {
      detailRoot.innerHTML = '<section class="case-not-found"><h1>没有找到这个案例</h1><p>案例可能已移动，或链接中的编号不正确。</p><a class="button button-secondary" href="index.html">返回案例社区</a></section>';
      return;
    }
    document.title = `${item.title} · WorkBuddy 案例`;
    detailRoot.innerHTML = `<section class="case-detail-hero"><a class="case-back" href="index.html">← 返回案例社区</a><div class="content-kicker">${escapeHtml(item.kind)} · ${escapeHtml(item.status)} · ${escapeHtml(item.version)}</div><h1>${escapeHtml(item.title)}</h1><p>${escapeHtml(item.summary)}</p><div class="case-detail-meta"><span><b>适用对象</b>${escapeHtml(item.audience)}</span><span><b>跟做用时</b>${escapeHtml(item.duration)}</span><span><b>目标产物</b>${escapeHtml(item.output)}</span></div></section>
      <div class="case-detail-layout"><nav class="case-detail-nav"><a href="#inputs">准备材料</a><a href="#steps">处理步骤</a><a href="#prompt">任务指令</a><a href="#checks">验收标准</a><a class="button button-small button-soft" href="${escapeHtml(item.learningPath)}">进入学习路径</a></nav><div class="case-detail-content">
      <section id="inputs" class="case-detail-section"><div class="content-kicker">01 / 准备</div><h2>开始前需要什么</h2><div class="case-input-list">${item.inputs.map(input => `<span>${escapeHtml(input)}</span>`).join('')}</div><div class="file-list">${item.files.map(file => `<div class="file-row"><span><strong>${escapeHtml(file.name)}</strong><span>${escapeHtml(file.note)}</span></span><a href="${escapeHtml(file.path)}" download>下载样例</a></div>`).join('')}</div></section>
      <section id="steps" class="case-detail-section"><div class="content-kicker">02 / 处理</div><h2>WorkBuddy 应该怎样推进</h2><div class="step-list">${item.steps.map((step, index) => `<div class="step-row"><span class="step-no">0${index + 1}</span><strong>${escapeHtml(step)}</strong><span>完成后再进入下一步，遇到口径不清时先停下来确认。</span></div>`).join('')}</div></section>
      <section id="prompt" class="case-detail-section"><div class="content-kicker">03 / 使用</div><h2>复制任务指令</h2><div class="prompt-panel" id="case-prompt">${escapeHtml(item.prompt)}<button class="copy-button" type="button" data-copy-target="#case-prompt" data-copy-message="案例指令已复制">复制</button></div></section>
      <section id="checks" class="case-detail-section"><div class="content-kicker">04 / 验收</div><h2>什么结果才算可用</h2><div class="review-grid"><div class="review-cell"><h3>逐项检查</h3><ul>${item.checks.map(check => `<li>${escapeHtml(check)}</li>`).join('')}</ul></div><div class="review-cell"><h3>适用限制</h3><p class="case-limitation">${escapeHtml(item.limitation)}</p></div></div></section>
      </div></div>`;
  };

  document.addEventListener('click', event => {
    const filter = event.target.closest('[data-case-filter]');
    if (!filter) return;
    activeFilter = filter.dataset.caseFilter;
    document.querySelectorAll('[data-case-filter]').forEach(button => button.classList.toggle('is-active', button === filter));
    renderList();
  });
  document.querySelector('#case-search')?.addEventListener('input', event => { query = event.target.value; renderList(); });

  const apiEnabled = new URLSearchParams(location.search).get('api') === '1'
    || window.localStorage?.getItem('workbuddyHubApi') === '1';
  const apiBase = (window.WORKBUDDY_HUB_API_URL || location.origin).replace(/\/$/, '');
  const requestedId = new URLSearchParams(location.search).get('id');
  const fromApi = apiEnabled && apiBase
    ? fetch(`${apiBase}/api/v1/artifacts?kind=case&limit=100`).then(response => response.ok ? response.json() : Promise.reject())
      .then(data => ({ cases: data.items || [] }))
    : Promise.reject();
  const fromStatic = fetch('../data/registry.json').then(response => response.ok ? response.json() : Promise.reject());
  (fromApi || fromStatic).catch(() => fromStatic).then(data => {
    cases = data.cases || [];
    const detailRequest = apiEnabled && apiBase && requestedId
      ? fetch(`${apiBase}/api/v1/artifacts/${encodeURIComponent(requestedId)}`).then(response => response.ok ? response.json() : Promise.reject()).catch(() => null)
      : Promise.resolve(null);
    return detailRequest.then(detail => ({ data, detail }));
  }).then(({ data, detail }) => {
    if (listRoot) renderList();
    if (detailRoot) renderDetail(normalizeDetail(detail || cases.find(item => item.id === requestedId)));
  }).catch(() => {
    if (listRoot) listRoot.innerHTML = '<div class="community-empty">案例数据加载失败，请通过本地服务打开页面。</div>';
    if (detailRoot) renderDetail(null);
  });
})();
