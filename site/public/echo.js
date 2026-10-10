"use strict";

(() => {
  const clips = ['a', 'b', 'c'];
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const players = new Set();
  const toggles = [...document.querySelectorAll('[data-echo-toggle]')];
  let userPaused = false;

  function mount(host) {
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.loop = false;
    video.preload = 'auto';
    video.hidden = true;
    video.className = 'echo-video';
    video.setAttribute('aria-hidden', 'true');
    host.append(video);
    host.classList.add('echo-avatar');

    let visible = false;
    let destroyed = false;
    let failed = false;
    let timer = null;
    let watchdog = null;
    let epoch = 0;
    let bag = [];
    let lastClip = null;
    let nextClip = null;
    const extension = video.canPlayType('video/webm; codecs="vp9"') ? 'webm' : 'mp4';

    function canRun() {
      return !destroyed && !failed && !userPaused && visible && !document.hidden && !reduced.matches
        && (window.RadhouseIcons?.effective() ?? true)
        && (!document.body.classList.contains('gallery-is-open') || Boolean(host.closest('dialog')));
    }

    function neutral(phase = 'neutral') {
      ++epoch;
      clearTimeout(timer);
      clearTimeout(watchdog);
      timer = watchdog = null;
      video.hidden = true;
      video.pause();
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

    function rest() {
      neutral();
      if (!canRun()) return;
      nextClip = chooseClip();
      const wait = 2000 + Math.random() * 4000;
      host.dataset.echoWait = String(wait);
      host.dataset.echoPhase = 'waiting';
      // Decode the next clip behind the neutral photograph during the rest.
      video.src = `/characters/echo-${nextClip}.${extension}`;
      video.load();
      timer = setTimeout(() => {
        timer = null;
        if (!canRun()) { neutral(); return; }
        host.dataset.echoPhase = 'starting';
        const ticket = epoch;
        watchdog = setTimeout(fail, 15000);
        video.play().catch(() => {
          if (ticket === epoch) fail();
        });
      }, wait);
    }

    video.addEventListener('playing', () => {
      if (!canRun()) return;
      clearTimeout(watchdog);
      watchdog = null;
      if (host.dataset.echoPhase !== 'starting') return;
      lastClip = nextClip;
      host.dataset.echoClip = lastClip;
      host.dataset.echoPhase = 'playing';
      video.hidden = false;
    });
    video.addEventListener('ended', () => {
      if (host.dataset.echoPhase === 'playing') rest();
    });
    video.addEventListener('error', () => {
      if (!destroyed && ['waiting', 'starting', 'playing'].includes(host.dataset.echoPhase)) fail();
    });
    video.addEventListener('waiting', () => {
      if (host.dataset.echoPhase === 'playing') {
        clearTimeout(watchdog);
        watchdog = setTimeout(fail, 15000);
      }
    });

    const player = {
      sync() {
        if (!canRun()) neutral(failed ? 'unavailable' : 'neutral');
        else if (host.dataset.echoPhase === 'neutral') rest();
      },
      destroy() {
        destroyed = true;
        neutral();
        observer.disconnect();
        players.delete(player);
        video.removeAttribute('src');
        video.load();
        video.remove();
        host.classList.remove('echo-avatar');
        delete host.dataset.echoPhase;
        delete host.dataset.echoClip;
        delete host.dataset.echoWait;
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
