(() => {
  const toast = document.querySelector('#toast');
  let toastTimer;

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('is-visible');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 2400);
  }

  async function copyText(text, message) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const helper = document.createElement('textarea');
      helper.value = text;
      helper.style.position = 'fixed';
      helper.style.opacity = '0';
      document.body.appendChild(helper);
      helper.select();
      document.execCommand('copy');
      helper.remove();
    }
    showToast(message || '已复制到剪贴板');
  }

  function activateTaskTab(button) {
    const group = button.closest('[data-tab-group]') || document;
    const target = button.dataset.taskTab;
    group.querySelectorAll('[data-task-tab]').forEach(item => {
      const active = item.dataset.taskTab === target;
      item.classList.toggle('is-active', active);
      item.setAttribute('aria-selected', String(active));
    });
    group.querySelectorAll('[data-task-panel]').forEach(panel => {
      const active = panel.dataset.taskPanel === target;
      panel.classList.toggle('is-hidden', !active);
      panel.hidden = !active;
    });
  }

  function setupProgress() {
    document.querySelectorAll('[data-progress-key]').forEach(input => {
      const key = `workbuddy-hub:${location.pathname}:${input.dataset.progressKey}`;
      try { input.checked = localStorage.getItem(key) === '1'; } catch { /* optional */ }
      input.closest('.practice-check')?.classList.toggle('is-done', input.checked);
      input.addEventListener('change', () => {
        try { localStorage.setItem(key, input.checked ? '1' : '0'); } catch { /* optional */ }
        input.closest('.practice-check')?.classList.toggle('is-done', input.checked);
      });
    });
  }

  function setupPdfReader() {
    const reader = document.querySelector('[data-pdf-reader]');
    if (!reader) return;
    const buttons = [...reader.querySelectorAll('[data-pdf-page]')];
    const image = reader.querySelector('#pdf-page-image');
    const title = reader.querySelector('#pdf-page-title');
    const counter = reader.querySelector('#pdf-page-counter');
    const initial = Math.min(Math.max(Number(new URLSearchParams(location.search).get('page')) || 1, 1), buttons.length);
    let current = initial - 1;

    const render = index => {
      current = (index + buttons.length) % buttons.length;
      const button = buttons[current];
      buttons.forEach((item, itemIndex) => {
        const active = itemIndex === current;
        item.classList.toggle('is-active', active);
        item.setAttribute('aria-current', active ? 'page' : 'false');
      });
      image.src = button.dataset.image;
      image.alt = `材料第 ${current + 1} 页：${button.dataset.title}`;
      title.textContent = button.dataset.title;
      counter.textContent = `${current + 1} / ${buttons.length}`;
      const url = new URL(location.href);
      url.searchParams.set('page', String(current + 1));
      history.replaceState({}, '', url);
    };

    reader.addEventListener('click', event => {
      const pageButton = event.target.closest('[data-pdf-page]');
      if (pageButton) render(buttons.indexOf(pageButton));
      if (event.target.closest('[data-pdf-prev]')) render(current - 1);
      if (event.target.closest('[data-pdf-next]')) render(current + 1);
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'ArrowLeft') render(current - 1);
      if (event.key === 'ArrowRight') render(current + 1);
    });
    render(current);
  }

  function setupVideo() {
    const video = document.querySelector('#workbuddy-video');
    if (!video) return;
    const chapters = [...document.querySelectorAll('[data-video-time]')];
    const initialTime = Math.max(Number(new URLSearchParams(location.search).get('t')) || 0, 0);
    let pendingTime = initialTime;

    const markChapter = currentTime => {
      let activeIndex = 0;
      chapters.forEach((chapter, index) => {
        if (currentTime >= Number(chapter.dataset.videoTime)) activeIndex = index;
      });
      chapters.forEach((chapter, index) => chapter.classList.toggle('is-active', index === activeIndex));
    };

    const applyPendingTime = () => {
      video.currentTime = Math.min(pendingTime, Math.max(video.duration - 1, 0));
      markChapter(pendingTime);
    };

    chapters.forEach(chapter => chapter.addEventListener('click', () => {
      pendingTime = Number(chapter.dataset.videoTime);
      markChapter(pendingTime);
      if (video.readyState >= 1) applyPendingTime();
      video.play().catch(() => {});
    }));
    if (video.readyState >= 1) applyPendingTime();
    else video.addEventListener('loadedmetadata', applyPendingTime, { once: true });
    video.addEventListener('timeupdate', () => markChapter(video.currentTime));
  }

  document.addEventListener('click', event => {
    const copyButton = event.target.closest('[data-copy-target]');
    if (copyButton) {
      const target = document.querySelector(copyButton.dataset.copyTarget);
      if (target) {
        const cleanTarget = target.cloneNode(true);
        cleanTarget.querySelectorAll('button').forEach(button => button.remove());
        copyText(cleanTarget.textContent.trim(), copyButton.dataset.copyMessage);
      }
    }
    const tabButton = event.target.closest('[data-task-tab]');
    if (tabButton) activateTaskTab(tabButton);
  });

  setupProgress();
  setupPdfReader();
  setupVideo();
})();
