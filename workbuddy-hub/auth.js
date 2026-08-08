(() => {
  const params = new URLSearchParams(location.search);
  const apiBase = (window.WORKBUDDY_HUB_API_URL || params.get('apiBase') || location.origin).replace(/\/$/, '');
  const apiHost = new URL(apiBase, location.href).hostname;
  const pageHost = location.hostname;
  const isLocal = ['127.0.0.1', 'localhost', '::1'].includes(apiHost)
    && ['127.0.0.1', 'localhost', '::1'].includes(pageHost);
  const configuredToken = typeof window.WORKBUDDY_ACCESS_TOKEN === 'string'
    ? window.WORKBUDDY_ACCESS_TOKEN.trim()
    : '';
  const configuredActor = isLocal
    ? (window.WORKBUDDY_ACTOR_ID || params.get('actor') || '').trim()
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
      ? '本地 PoC 需要配置 actor 才能执行协作操作。'
      : '当前页面需要通过组织 SSO 登录后才能访问受保护数据。'
  });
})();
