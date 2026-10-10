"use strict";

(() => {
  const clips = ['a', 'b', 'c'];
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const players = new Set();
  const toggles = [...document.querySelectorAll('[data-echo-toggle]')];
  let userPaused = false;

  function mount(host) {
    const videos = clips.map(clip => {
      const video = document.createElement('video');
      video.muted = true;
      video.playsInline = true;
      video.loop = false;
      video.preload = 'none';
      video.className = 'echo-video';
      video.dataset.clip = clip;
      video.setAttribute('aria-hidden', 'true');
      host.append(video);
      return video;
    });
    host.classList.add('echo-avatar');

    let visible = false;
    let destroyed = false;
    let failed = false;
    let prepared = false;
    let watchdog = null;
    let epoch = 0;
    let bag = [];
    let lastClip = null;
    let active = null;
    let incoming = null;
    const extension = videos[0].canPlayType('video/webm; codecs="vp9"') ? 'webm' : 'mp4';

    function canRun() {
      return !destroyed && !failed && !userPaused && visible && !document.hidden && !reduced.matches
        && (window.RadhouseIcons?.effective() ?? true)
        && (!document.body.classList.contains('gallery-is-open') || Boolean(host.closest('dialog')));
    }

    function neutral(phase = 'neutral') {
      ++epoch;
      clearTimeout(watchdog);
      watchdog = null;
      incoming = active = null;
      for (const video of videos) {
        video.pause();
        video.classList.remove('is-active');
      }
      host.dataset.echoPhase = phase;
    }

    function chooseClip() {
      if (!bag.length) {
        bag = [...clips];
        for (let i = bag.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [bag[i], bag[j]] = [bag[j], bag[i]];
        }
      }
      if (bag[0] === lastClip) {
        if (bag.length === 1) { bag = []; return chooseClip(); }
        [bag[0], bag[1]] = [bag[1], bag[0]];
      }
      return bag.shift();
    }

    function fail() {
      failed = true;
      neutral('unavailable');
    }

    function start() {
      if (!canRun()) { neutral(); return; }
      if (!prepared) {
        prepared = true;
        // Preload all three reactions so the next can start at once.
        for (const video of videos) {
          video.preload = 'auto';
          video.src = `/characters/echo-${video.dataset.clip}.${extension}`;
          video.load();
        }
      }
      const clip = chooseClip();
      incoming = videos[clips.indexOf(clip)];
      incoming.currentTime = 0;
      host.dataset.echoPhase = 'starting';
      const ticket = ++epoch;
      clearTimeout(watchdog);
      watchdog = setTimeout(fail, 15000);
      incoming.play().catch(() => {
        if (ticket === epoch) fail();
      });
    }

    for (const video of videos) {
      video.addEventListener('playing', () => {
        if (!canRun() || (video !== incoming && video !== active)) return;
        clearTimeout(watchdog);
        watchdog = null;
        if (video !== incoming || host.dataset.echoPhase !== 'starting') return;
        // Retain the previous clip's final frame until the next is playing.
        active?.classList.remove('is-active');
        active?.pause();
        active = video;
        incoming = null;
        video.classList.add('is-active');
        lastClip = video.dataset.clip;
        host.dataset.echoClip = lastClip;
        host.dataset.echoPhase = 'playing';
      });
      video.addEventListener('ended', () => {
        if (video === active && host.dataset.echoPhase === 'playing') start();
      });
      video.addEventListener('error', () => {
        if (!destroyed && prepared) fail();
      });
      video.addEventListener('waiting', () => {
        if (video === active || video === incoming) {
          clearTimeout(watchdog);
          watchdog = setTimeout(fail, 15000);
        }
      });
    }

    const player = {
      sync() {
        if (!canRun()) neutral(failed ? 'unavailable' : 'neutral');
        else if (host.dataset.echoPhase === 'neutral') start();
      },
      destroy() {
        destroyed = true;
        neutral();
        observer.disconnect();
        players.delete(player);
        for (const video of videos) {
          video.removeAttribute('src');
          video.load();
          video.remove();
        }
        host.classList.remove('echo-avatar');
        delete host.dataset.echoPhase;
        delete host.dataset.echoClip;
      }
    };
    const observer = new IntersectionObserver(entries => {
      visible = entries.some(entry => entry.isIntersecting);
      player.sync();
    });
    players.add(player);
    neutral();
    observer.observe(host);
    return player;
  }

  function refresh() {
    for (const player of players) player.sync();
    for (const toggle of toggles) {
      const dialog = toggle.closest('dialog');
      toggle.hidden = reduced.matches || Boolean(dialog && !dialog.querySelector('.gallery-portrait-frame.echo-avatar'));
      toggle.textContent = userPaused ? 'Play Echo' : 'Pause Echo';
      toggle.setAttribute('aria-pressed', String(userPaused));
    }
  }
  for (const toggle of toggles) toggle.addEventListener('click', () => {
    userPaused = !userPaused;
    refresh();
  });
  document.addEventListener('visibilitychange', refresh);
  document.addEventListener('radhouse-appearance', refresh);
  reduced.addEventListener('change', refresh);
  window.RadhouseEcho = Object.freeze({mount, refresh});
  for (const host of document.querySelectorAll('[data-echo-avatar]')) mount(host);
  refresh();
})();
