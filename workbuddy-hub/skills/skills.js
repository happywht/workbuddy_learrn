(() => {
  const queryInput = document.querySelector('#skill-query');
  const form = document.querySelector('#skill-search-form');
  const resultsRoot = document.querySelector('#skill-results');
  const status = document.querySelector('#skill-status');
  const statusNote = document.querySelector('#skill-status-note');
  const statusDot = document.querySelector('#skill-status-dot');
  const params = new URLSearchParams(location.search);
  const auth = window.WorkBuddyAuth;
  const apiBase = auth?.apiBase || (window.WORKBUDDY_HUB_API_URL || params.get('apiBase') || location.origin).replace(/\/$/, '');
  const actorHeaders = () => auth?.headers() || {};

  const escapeHtml = (value = '') => String(value)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');

  const setStatus = (connected, title, note) => {
    status.textContent = title;
    statusNote.textContent = note;
    statusDot.classList.toggle('is-online', connected);
  };

  const render = items => {
    if (!items.length) {
      resultsRoot.innerHTML = '<div class="skill-empty">没有找到可访问的 Skill。</div>';
      return;
    }
    resultsRoot.innerHTML = items.map(item => `<article class="skill-row">
      <div class="skill-row-main"><div class="skill-row-top"><span>${escapeHtml(item.provider)}</span><strong>${escapeHtml(item.current_version || '版本未知')}</strong></div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.summary)}</p><div class="case-tags">${(item.tags || []).map(tag => `<span>${escapeHtml(tag)}</span>`).join('')}</div></div>
      <div class="skill-row-actions"><button type="button" class="button button-secondary skill-plan" data-artifact-id="${escapeHtml(item.id)}" data-slug="${escapeHtml(item.id.replace(/^skillhub:/, ''))}">生成安装计划</button></div>
    </article>`).join('');
  };

  const search = async query => {
    if (!apiBase) {
      setStatus(false, 'Hub API 未配置', auth?.loginRequiredMessage || '当前页面不会伪造 SkillHub 数据');
      resultsRoot.innerHTML = '<div class="skill-empty">请通过 Hub 门户配置 API 地址后再查询。</div>';
      return;
    }
    resultsRoot.innerHTML = '<div class="skill-empty">正在查询 SkillHub...</div>';
    try {
      const response = await fetch(`${apiBase}/api/v1/artifacts?kind=skill&q=${encodeURIComponent(query)}&limit=50`, {headers: actorHeaders()});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      setStatus(true, 'Hub API 已连接', '结果经过 SkillHub 权限边界过滤');
      render(payload.items || []);
    } catch (error) {
      setStatus(false, 'SkillHub 暂不可用', error.message || '请稍后重试');
      resultsRoot.innerHTML = '<div class="skill-empty">查询失败。请检查连接、身份和 SkillHub 状态。</div>';
    }
  };

  form.addEventListener('submit', event => { event.preventDefault(); const query = queryInput.value.trim(); if (query) search(query); });
  resultsRoot.addEventListener('click', async event => {
    const button = event.target.closest('.skill-plan');
    if (!button || !apiBase) return;
    button.disabled = true;
    try {
      const response = await fetch(`${apiBase}/api/v1/artifacts/${encodeURIComponent(button.dataset.artifactId)}/install-plans`, {
        method: 'POST', headers: {'Content-Type': 'application/json', ...actorHeaders()}, body: JSON.stringify({slug: button.dataset.slug, target_agent: 'workbuddy'})
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      window.alert(`版本 ${payload.version} 已固定。\n校验和：${payload.sha256}\n\n安装目录：${payload.install_directory}`);
    } catch (error) { window.alert(`安装计划生成失败：${error.message || '未知错误'}`); }
    finally { button.disabled = false; }
  });
})();
