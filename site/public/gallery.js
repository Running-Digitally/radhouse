"use strict";

(() => {
  const icons = window.RadhouseIcons;
  if (icons) {
    for (const host of document.querySelectorAll('[data-site-icon]')) {
      host.append(icons.create(host.dataset.siteIcon));
      const target = host.closest('a, button, .workspace-card, .browser-handover li') || host;
      target.addEventListener('pointerenter', event => {
        if (event.pointerType !== 'touch') icons.hover(host);
      });
      target.addEventListener('focus', () => icons.hover(host));
    }
  }

  const dialog = document.querySelector('#character-gallery');
  const dataElement = document.querySelector('#character-gallery-data');
  if (!dialog || !dataElement || typeof dialog.showModal !== 'function') return;
  const catalog = JSON.parse(dataElement.content.textContent);
  const themes = catalog.themes;
  const profiles = catalog.profiles;
  const themeGroup = dialog.querySelector('.gallery-themes');
  const characterGroup = dialog.querySelector('.gallery-characters');
  const featured = dialog.querySelector('.gallery-featured');
  const photo = dialog.querySelector('#gallery-portrait');
  const portraitFrame = dialog.querySelector('.gallery-portrait-frame');
  const name = dialog.querySelector('#gallery-character-name');
  const role = dialog.querySelector('#gallery-character-role');
  const story = dialog.querySelector('#gallery-character-story');
  const description = dialog.querySelector('#gallery-theme-description');
  const collection = dialog.querySelector('#gallery-collection-name');
  const announcement = dialog.querySelector('#gallery-announcement');
  const close = dialog.querySelector('#gallery-close');
  const previous = dialog.querySelector('#gallery-previous');
  const next = dialog.querySelector('#gallery-next');
  let currentTheme = themes[0];
  let currentProfile = profiles.find(profile => profile.id === currentTheme.cover);
  let opener = null;
  let portraitAnimation = null;
  let echoPortrait = null;

  function portraitSource(profile) {
    return profile.id === 'echo' ? '/characters/echo-neutral.png' : `/characters/${profile.id}.webp`;
  }

  if (icons) {
    icons.decorate(close, 'close', 'Close character gallery', {compact: true});
    icons.decorate(previous, 'back', 'Previous character', {compact: true});
    icons.decorate(next, 'forward', 'Next character', {compact: true});
  }

  function themeProfiles() {
    return profiles.filter(profile => profile.theme === currentTheme.id);
  }

  function renderProfile(profile, animate = true) {
    currentProfile = profile;
    echoPortrait?.destroy();
    echoPortrait = null;
    photo.src = portraitSource(profile);
    photo.alt = `${profile.name}, ${currentTheme.style.toLowerCase()} character`;
    if (profile.id === 'echo') echoPortrait = window.RadhouseEcho?.mount(portraitFrame);
    name.textContent = profile.name;
    role.textContent = profile.role;
    story.textContent = profile.story;
    for (const button of characterGroup.querySelectorAll('button')) {
      button.setAttribute('aria-pressed', String(button.dataset.character === profile.id));
    }
    const position = themeProfiles().findIndex(item => item.id === profile.id) + 1;
    announcement.textContent = `${profile.name}. ${currentTheme.name}. Character ${position} of ${themeProfiles().length}.`;
    portraitAnimation?.cancel();
    portraitAnimation = null;
    if (animate && icons?.effective()) {
      portraitAnimation = featured.animate([
        {opacity: .55, transform: 'translateY(5px)'},
        {opacity: 1, transform: 'translateY(0)'}
      ], {duration: 220, easing: 'ease-out'});
    }
    window.RadhouseEcho?.refresh();
  }

  function chooseTheme(theme, animate = true) {
    currentTheme = theme;
    dialog.dataset.theme = theme.id;
    collection.textContent = theme.name;
    description.textContent = theme.description;
    for (const button of themeGroup.querySelectorAll('button')) {
      button.setAttribute('aria-pressed', String(button.dataset.theme === theme.id));
    }
    characterGroup.replaceChildren();
    for (const profile of themeProfiles()) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'gallery-character';
      button.dataset.character = profile.id;
      button.setAttribute('aria-label', `Preview ${profile.name}`);
      button.setAttribute('aria-pressed', 'false');
      const image = document.createElement('img');
      image.src = portraitSource(profile);
      image.width = 96;
      image.height = 96;
      image.alt = '';
      image.decoding = 'async';
      const label = document.createElement('span');
      label.textContent = profile.name;
      const thumbnail = document.createElement('span');
      thumbnail.className = 'gallery-thumbnail';
      thumbnail.append(image);
      button.append(thumbnail, label);
      button.addEventListener('click', () => renderProfile(profile));
      characterGroup.append(button);
    }
    renderProfile(profiles.find(profile => profile.id === theme.cover), animate);
  }

  for (const theme of themes) {
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.theme = theme.id;
    button.textContent = theme.name;
    button.setAttribute('aria-pressed', 'false');
    button.addEventListener('click', () => chooseTheme(theme));
    themeGroup.append(button);
  }

  function moveCharacter(direction) {
    const options = themeProfiles();
    const index = options.findIndex(profile => profile.id === currentProfile.id);
    renderProfile(options[(index + direction + options.length) % options.length]);
  }
  previous.addEventListener('click', () => moveCharacter(-1));
  next.addEventListener('click', () => moveCharacter(1));
  close.addEventListener('click', () => dialog.close());

  for (const link of document.querySelectorAll('[data-gallery-open]')) {
    link.setAttribute('aria-haspopup', 'dialog');
    link.setAttribute('aria-controls', dialog.id);
    link.addEventListener('click', event => {
      // Preserve ordinary browser link gestures for the static fallback.
      if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const theme = themes.find(item => item.id === link.dataset.galleryOpen);
      if (!theme) return;
      event.preventDefault();
      opener = link;
      chooseTheme(theme, false);
      const profile = themeProfiles().find(item => item.id === link.dataset.galleryCharacter);
      if (profile) renderProfile(profile, false);
      dialog.showModal();
      document.body.classList.add('gallery-is-open');
      window.RadhouseEcho?.refresh();
    });
  }

  dialog.addEventListener('close', () => {
    portraitAnimation?.cancel();
    portraitAnimation = null;
    document.body.classList.remove('gallery-is-open');
    echoPortrait?.destroy();
    echoPortrait = null;
    window.RadhouseEcho?.refresh();
    opener?.focus({preventScroll: true});
    opener = null;
  });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  dialog.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const group = event.target.closest('.gallery-themes, .gallery-characters');
    if (!group) return;
    const buttons = [...group.querySelectorAll('button')];
    const index = buttons.indexOf(event.target);
    if (index < 0) return;
    event.preventDefault();
    const target = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
      : (index + (event.key === 'ArrowLeft' ? -1 : 1) + buttons.length) % buttons.length;
    buttons[target].focus();
    buttons[target].click();
  });
  document.addEventListener('radhouse-appearance', event => {
    if (!event.detail.effective) portraitAnimation?.cancel();
  });

  document.querySelector('#characters').classList.add('gallery-enhanced');
  const deepLink = [...document.querySelectorAll('[data-gallery-open]')]
    .find(link => link.getAttribute('href') === location.hash);
  if (deepLink) deepLink.click();
})();
