/* One conversation over time. The illustration never makes a network request. */
(() => {
  const journey = document.getElementById('conversation-example');
  if (!journey) return;
  const tabs = [...journey.querySelectorAll('[role="tab"]')];
  const panels = tabs.map(tab => document.getElementById(tab.getAttribute('aria-controls')));
  const next = journey.querySelector('.journey-next');
  const status = journey.querySelector("#journey-status");
  const drawingDescription = document.getElementById('journey-art-desc');
  const actions = ['See the reply', 'Step away', 'Come back', 'Start again'];
  const descriptions = [
    'A notebook holds your question about a small garden. The day begins, and your private conversation has a place to stay.',
    'The assistant reply appears beneath your question in the notebook. The earlier thought and the answer stay together.',
    'Day turns to night. A note says Back tomorrow. The notebook stays open with the same question and reply, illustrating retained context.',
    'Daylight returns. The same notebook still holds the exchange, with a new note asking about a shady corner.'
  ];
  let selected = 0;
  function select(index, focus = false, source = 'step') {
    const changed = selected !== index;
    selected = index;
    journey.dataset.step = String(index);
    tabs.forEach((tab, i) => {
      tab.setAttribute('aria-selected', String(i === index));
      tab.tabIndex = i === index ? 0 : -1;
      panels[i].hidden = i !== index;
    });
    next.querySelector('.action-label').textContent = actions[index];
    next.querySelector('[aria-hidden]').textContent = index === 3 ? '↺' : '→';
    drawingDescription.textContent = descriptions[index];
    if (changed) {
      status.textContent = `Step ${index + 1} of 4. ${panels[index].querySelector('h2').textContent}`;
      window.dispatchEvent(new CustomEvent('radhouse:interaction', {
        detail: { name: 'conversation_example_step_selected', properties: { step: tabs[index].dataset.stepName, source } }
      }));
    }
    if (focus) tabs[index].focus({ preventScroll: true });
  }
  journey.querySelector('.journey-controls').hidden = false;
  next.hidden = false;
  next.addEventListener('click', () => select((selected + 1) % tabs.length, false, 'next'));
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(index));
    tab.addEventListener('keydown', event => {
      const indexToSelect = {
        ArrowRight: (index + 1) % tabs.length,
        ArrowLeft: (index + tabs.length - 1) % tabs.length,
        Home: 0,
        End: tabs.length - 1
      }[event.key];
      if (indexToSelect !== undefined) { event.preventDefault(); select(indexToSelect, true, 'keyboard'); }
    });
  });
  select(0);
})();
