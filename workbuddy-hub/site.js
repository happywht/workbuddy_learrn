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

  function setupCoursePlayer() {
    const video = document.querySelector('#bluebook-video');
    if (!video) return;
    const chapters = [...document.querySelectorAll('[data-course-chapter]')];
    const title = document.querySelector('#course-video-title');
    const summary = document.querySelector('#course-video-summary');
    const duration = document.querySelector('#course-video-duration');
    const openSource = document.querySelector('#course-open-source');
    const requested = Number(new URLSearchParams(location.search).get('chapter')) || 1;

    const selectChapter = (index, autoplay = false) => {
      const safeIndex = Math.min(Math.max(index, 0), chapters.length - 1);
      const chapter = chapters[safeIndex];
      chapters.forEach((item, itemIndex) => {
        const active = itemIndex === safeIndex;
        item.classList.toggle('is-active', active);
        item.setAttribute('aria-current', active ? 'true' : 'false');
      });
      video.pause();
      video.poster = chapter.dataset.poster;
      video.src = chapter.dataset.courseSrc;
      video.load();
      title.textContent = chapter.dataset.title;
      summary.textContent = chapter.dataset.summary;
      duration.textContent = chapter.dataset.duration;
      openSource.href = chapter.dataset.courseSrc;
      const url = new URL(location.href);
      url.searchParams.set('chapter', String(safeIndex + 1));
      history.replaceState({}, '', url);
      if (autoplay) video.play().catch(() => {});
    };

    chapters.forEach((chapter, index) => chapter.addEventListener('click', () => selectChapter(index, true)));
    video.addEventListener('ended', () => {
      const activeIndex = chapters.findIndex(chapter => chapter.classList.contains('is-active'));
      if (activeIndex >= 0 && activeIndex < chapters.length - 1) selectChapter(activeIndex + 1, true);
    });
    selectChapter(Math.min(Math.max(requested - 1, 0), chapters.length - 1));
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

  function setupScrollSpy() {
    const nav = document.querySelector('.local-nav');
    if (!nav) return;
    const links = [...nav.querySelectorAll('a[href^="#"]')];
    const targets = links.map(link => {
      const id = link.getAttribute('href').slice(1);
      return document.getElementById(id);
    }).filter(Boolean);
    if (targets.length === 0) return;

    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          const activeLink = links.find(link => link.getAttribute('href') === `#${entry.target.id}`);
          links.forEach(link => link.classList.remove('is-active'));
          if (activeLink) activeLink.classList.add('is-active');
        }
      });
    }, { rootMargin: '-15% 0px -55% 0px', threshold: 0 });

    targets.forEach(target => observer.observe(target));
  }

  function setupBackToTop() {
    let button = document.querySelector('.back-to-top');
    if (!button) {
      button = document.createElement('button');
      button.className = 'back-to-top';
      button.setAttribute('type', 'button');
      button.setAttribute('aria-label', '返回顶部');
      button.textContent = '↑';
      document.body.appendChild(button);
    }

    const toggle = () => {
      button.classList.toggle('is-visible', window.scrollY > 400);
    };

    window.addEventListener('scroll', toggle, { passive: true });
    button.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    toggle();
  }

  setupProgress();
  setupPdfReader();
  setupCoursePlayer();
  setupScrollSpy();
  setupBackToTop();
})();
