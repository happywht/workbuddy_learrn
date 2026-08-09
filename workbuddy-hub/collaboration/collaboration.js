(() => {
  const params = new URLSearchParams(location.search);
  const auth = window.WorkBuddyAuth;
  const apiBase = auth?.apiBase || (window.WORKBUDDY_HUB_API_URL || params.get('apiBase') || location.origin).replace(/\/$/, '');
  const form = document.querySelector('#collab-form');
  const teamSelect = document.querySelector('#collab-team');
  const goalInput = document.querySelector('#collab-goal');
  const taskRoot = document.querySelector('#collab-task-body');
  const status = document.querySelector('#collab-status');
  const statusNote = document.querySelector('#collab-status-note');
  const statusDot = document.querySelector('#collab-status-dot');
  let activeTaskId = null;
  let activeTask = null;
  let activeArtifacts = [];
  let activeEvents = [];
  let eventCursor = 0;
  let pollTimer = null;
  let waitController = null;
  const terminalStatuses = new Set(['completed', 'failed', 'cancelled', 'timed_out']);

  const escapeHtml = (value = '') => String(value)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
  const headers = extra => auth?.headers(extra) || {...extra};
  const setConnection = (online, title, note) => {
    status.textContent = title; statusNote.textContent = note; statusDot.classList.toggle('is-online', online);
  };
  const api = async (path, options = {}) => {
    const response = await fetch(`${apiBase}${path}`, {...options, headers: headers(options.headers || {})});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.detail || `HTTP ${response.status}`);
      error.code = payload.detail;
      throw error;
    }
    return payload;
  };
  const renderTask = task => {
    activeTask = task;
    const inputPrompt = [...activeEvents].reverse()
      .map(event => event?.payload?.content?.body || event?.payload?.body || event?.payload?.message)
      .find(value => typeof value === 'string' && value.trim()) || '协作 Agent 需要你补充信息后才能继续。';
    const inputSection = task.status === 'input_required'
      ? `<section class="collab-input-request"><h4>需要人工输入</h4><p>${escapeHtml(inputPrompt)}</p><label for="collab-input">回复协作室</label><textarea id="collab-input" rows="4" maxlength="12000" placeholder="补充事实、选择或确认边界"></textarea><button type="button" class="button button-primary" id="collab-send">发送回复</button></section>`
      : '';
    const artifactRows = activeArtifacts.map(item => {
      const verification = item.content_verified
        ? `完整性已验证 · ${escapeHtml(item.detected_media_type || item.media_type)} · ${item.actual_size ?? item.size ?? '大小未知'} bytes`
        : item.verification_status === 'failed'
          ? `校验失败 · ${escapeHtml(item.verification_error || '未知错误')}`
          : `${escapeHtml(item.media_type)} · ${item.size == null ? '大小未知' : `${item.size} bytes`} · 内容待校验`;
      const action = item.content_verified ? '' : `<button type="button" class="artifact-verify" data-artifact-id="${escapeHtml(item.artifact_id)}">验证内容</button>`;
      return `<li><div><strong>${escapeHtml(item.name)}</strong><span>${verification}</span></div>${action}</li>`;
    }).join('');
    const artifactSection = artifactRows ? `<section class="collab-artifacts"><h4>任务产物</h4><ul>${artifactRows}</ul></section>` : '';
    taskRoot.className = 'collab-task-body';
    taskRoot.innerHTML = `<div class="collab-task-meta"><span><b>Hub 状态</b>${escapeHtml(task.status)}</span><span><b>Hub ID</b>${escapeHtml(task.task_id)}</span><span><b>Matrix 事件</b>${escapeHtml(task.dispatch_event_id || task.external_task_id || '等待投递')}</span></div><h3>${escapeHtml(task.goal)}</h3>${inputSection}${artifactSection}<div class="collab-task-actions"><button type="button" class="button button-secondary" id="collab-refresh">刷新状态</button><button type="button" class="button button-soft" id="collab-cancel">请求取消</button></div>`;
  };
  const mergeArtifacts = items => {
    const merged = new Map(activeArtifacts.map(item => [item.artifact_id, item]));
    (items || []).forEach(item => merged.set(item.artifact_id, item));
    activeArtifacts = [...merged.values()];
  };
  const mergeEvents = items => {
    const merged = new Map(activeEvents.map(item => [item.event_id, item]));
    (items || []).forEach(item => merged.set(item.event_id, item));
    activeEvents = [...merged.values()];
  };
  const refresh = async () => {
    if (!activeTaskId) return;
    try {
      const task = await api(`/api/v1/collaboration/tasks/${encodeURIComponent(activeTaskId)}`);
      renderTask(task);
    }
    catch (error) { setConnection(false, '状态读取失败', error.message); }
  };
  const waitForUpdates = async () => {
    if (!activeTaskId || terminalStatuses.has(activeTask?.status)) return;
    const controller = new AbortController();
    waitController = controller;
    try {
      const result = await api(`/api/v1/collaboration/tasks/${encodeURIComponent(activeTaskId)}/wait?cursor=${eventCursor}&timeout_seconds=20`, {signal: controller.signal});
      if (controller.signal.aborted) return;
      eventCursor = result.next_cursor;
      mergeEvents(result.events);
      mergeArtifacts(result.artifacts);
      renderTask(result.task);
      setConnection(result.sync.status !== 'degraded', result.sync.status === 'degraded' ? 'Matrix 同步降级' : 'AgentTeams 已连接', result.sync.error || `任务状态：${result.task.status}`);
    } catch (error) {
      if (error.name !== 'AbortError') setConnection(false, '状态等待失败', error.message);
    } finally {
      if (waitController === controller) waitController = null;
      if (!controller.signal.aborted && activeTaskId && !terminalStatuses.has(activeTask?.status)) {
        pollTimer = window.setTimeout(waitForUpdates, 300);
      }
    }
  };
  const loadTeams = async () => {
    if (!apiBase || !auth?.isAuthenticated) { setConnection(false, '需要登录', auth?.loginRequiredMessage || '需要 Hub API 地址和登录身份'); return; }
    try {
      const payload = await api('/api/v1/collaboration/teams');
      const teams = payload.teams || payload.items || [];
      const readyTeams = teams.filter(team => team.hubDispatch?.ready);
      teamSelect.innerHTML = readyTeams.length ? readyTeams.map(team => `<option value="${escapeHtml(team.name)}">${escapeHtml(team.teamName || team.name)}</option>`).join('') : '<option value="">当前身份没有可投递的 Team</option>';
      setConnection(readyTeams.length > 0, readyTeams.length ? 'AgentTeams 已连接' : 'Matrix 投递未就绪', `${readyTeams.length} / ${teams.length} 个 Team 可投递`);
    } catch (error) {
      if (error.code === 'agentteams_controller_not_configured') {
        setConnection(false, 'AgentTeams 未配置', 'Hub API 已连接 · agentteams_controller_not_configured');
        teamSelect.innerHTML = '<option value="">本地尚未配置 AgentTeams</option>';
        return;
      }
      setConnection(false, 'AgentTeams 暂不可用', error.message);
    }
  };
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (!apiBase || !auth?.isAuthenticated || !teamSelect.value) return;
    const button = form.querySelector('button[type="submit"]'); button.disabled = true;
    try {
      const task = await api('/api/v1/collaboration/tasks', {method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID()}, body: JSON.stringify({team_id: teamSelect.value, goal: goalInput.value.trim(), output_contract: {type: 'report'}})});
      activeTaskId = task.task_id; activeArtifacts = []; activeEvents = []; eventCursor = 0; renderTask(task); waitForUpdates();
    } catch (error) { setConnection(false, '任务创建失败', error.message); }
    finally { button.disabled = false; }
  });
  taskRoot.addEventListener('click', async event => {
    const verifyButton = event.target.closest('.artifact-verify');
    if (verifyButton && activeTaskId) {
      verifyButton.disabled = true;
      try {
        const artifact = await api(`/api/v1/collaboration/tasks/${encodeURIComponent(activeTaskId)}/artifacts/${encodeURIComponent(verifyButton.dataset.artifactId)}/verify`, {method: 'POST', headers: {'Idempotency-Key': crypto.randomUUID()}});
        mergeArtifacts([artifact]); renderTask(activeTask);
      } catch (error) { setConnection(false, '产物校验失败', error.message); }
      finally { if (verifyButton.isConnected) verifyButton.disabled = false; }
      return;
    }
    if (event.target.closest('#collab-refresh')) await refresh();
    if (event.target.closest('#collab-send') && activeTaskId) {
      const input = document.querySelector('#collab-input');
      const content = input?.value.trim() || '';
      if (!content) return;
      const sendButton = event.target.closest('#collab-send');
      sendButton.disabled = true;
      try {
        await api(`/api/v1/collaboration/tasks/${encodeURIComponent(activeTaskId)}/messages`, {method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID()}, body: JSON.stringify({content})});
        await refresh();
        setConnection(true, '已发送人工输入', '协作 Agent 将继续处理');
      } catch (error) { setConnection(false, '人工输入发送失败', error.message); }
      finally { if (sendButton.isConnected) sendButton.disabled = false; }
      return;
    }
    if (event.target.closest('#collab-cancel') && activeTaskId) {
      try { const result = await api(`/api/v1/collaboration/tasks/${encodeURIComponent(activeTaskId)}/cancel`, {method: 'POST', headers: {'Idempotency-Key': crypto.randomUUID()}}); await refresh(); if (terminalStatuses.has(result.status)) clearTimeout(pollTimer); }
      catch (error) { setConnection(false, '取消请求失败', error.message); }
    }
  });
  window.addEventListener('beforeunload', () => { clearTimeout(pollTimer); waitController?.abort(); });
  loadTeams();
})();
