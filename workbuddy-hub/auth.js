(() => {
  const params = new URLSearchParams(location.search);
  const localHosts = new Set(['127.0.0.1', 'localhost', '::1']);
  const isLocalPage = localHosts.has(location.hostname);
  const localApiDefault = 'http://127.0.0.1:8100';
  const apiBase = (window.WORKBUDDY_HUB_API_URL || params.get('apiBase') || (isLocalPage ? localApiDefault : location.origin)).replace(/\/$/, '');
  const apiHost = new URL(apiBase, location.href).hostname;
  const isLocal = isLocalPage && localHosts.has(apiHost);
  const configuredToken = typeof window.WORKBUDDY_ACCESS_TOKEN === 'string'
    ? window.WORKBUDDY_ACCESS_TOKEN.trim()
    : '';
  const configuredActor = isLocal
    ? (window.WORKBUDDY_ACTOR_ID || params.get('actor') || 'local-dev').trim()
    : '';

  window.WorkBuddyAuth = Object.freeze({
    apiBase,
    isLocal,
    hasBearer: Boolean(configuredToken),
    hasLocalActor: Boolean(configuredActor),
    isAuthenticated: Boolean(configuredToken || configuredActor),
    headers(extra = {}) {
      if (configuredToken) return {...extra, Authorization: `Bearer ${configuredToken}`};
      if (configuredActor) return {...extra, 'X-Actor-Id': configuredActor};
      return {...extra};
    },
    loginRequiredMessage: isLocal
      ? '本地开发身份不可用，请检查 actor 参数。'
      : '当前页面需要通过组织 SSO 登录后才能访问受保护数据。'
  });
})();
