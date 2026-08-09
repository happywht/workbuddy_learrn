(() => {
  const params = new URLSearchParams(location.search);
  const auth = window.WorkBuddyAuth;
  const apiBase = (auth?.apiBase || window.WORKBUDDY_HUB_API_URL || params.get('apiBase') || location.origin).replace(/\/$/, '');
  const status = document.querySelector('#market-status');
  const statusNote = document.querySelector('#market-status-note');
  const statusDot = document.querySelector('#market-status-dot');
  const list = document.querySelector('#market-task-list');
  document.querySelector('#api-base-label').textContent = apiBase;
  document.querySelectorAll('code').forEach(node => { node.textContent = node.textContent.replaceAll('http://127.0.0.1:8100', apiBase); });

  const escapeHtml = (value = '') => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  const setStatus = (online, title, note) => { status.textContent = title; statusNote.textContent = note; statusDot.classList.toggle('is-online', online); };
  const loadTasks = async () => {
    list.innerHTML = '<div class="skill-empty">正在读取任务...</div>';
    try {
      const response = await fetch(`${apiBase}/api/v1/tasks?status=published&limit=20`, {headers: auth?.headers?.() || {}});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      setStatus(true, 'Hub API 已连接', `${payload.total || 0} 个公开任务`);
      if (!payload.items?.length) { list.innerHTML = '<div class="skill-empty">当前没有公开任务。</div>'; return; }
      list.innerHTML = payload.items.map(task => `<article class="market-task"><div><span class="market-task-status">${escapeHtml(task.status)}</span><h3>${escapeHtml(task.title)}</h3><p>${escapeHtml(task.goal)}</p><div class="case-tags">${(task.required_capabilities || []).map(item => `<span>${escapeHtml(item)}</span>`).join('')}${(task.required_skills || []).map(item => `<span>${escapeHtml(item)}</span>`).join('')}</div></div><code>${escapeHtml(task.id)}</code></article>`).join('');
    } catch (error) { setStatus(false, 'Hub API 暂不可用', error.message); list.innerHTML = '<div class="skill-empty">无法读取任务，请检查 Hub API。</div>'; }
  };
  document.querySelector('#refresh-tasks').addEventListener('click', loadTasks);
  document.querySelectorAll('.copy-code').forEach(button => button.addEventListener('click', async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    const text = target.innerText;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const fallback = document.createElement('textarea');
      fallback.value = text;
      fallback.setAttribute('readonly', '');
      fallback.style.position = 'fixed';
      fallback.style.opacity = '0';
      document.body.appendChild(fallback);
      fallback.select();
      document.execCommand('copy');
      fallback.remove();
    }
    const original = button.textContent; button.textContent = '已复制'; setTimeout(() => { button.textContent = original; }, 1200);
  }));
  loadTasks();
})();
