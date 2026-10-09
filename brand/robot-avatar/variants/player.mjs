// Small-avatar preview: held neutral frame, random rest, shuffled one-shot clips.
// The incoming video is decoded behind the held frame before it becomes visible.
const root = new URL('../', import.meta.url);
const manifest = await fetch(new URL('manifest.json', import.meta.url)).then(r => {
  if (!r.ok) throw new Error('Could not load the avatar manifest');
  return r.json();
});
const slots = [...document.querySelectorAll('.avatar-slot')];
const canvases = [...document.querySelectorAll('.size-preview')];
const status = document.querySelector('#status');
const countdown = document.querySelector('#countdown');
const toggle = document.querySelector('#toggle');
const historyList = document.querySelector('#history');
const errorLabel = document.querySelector('#error');
const motion = matchMedia('(prefers-reduced-motion: reduce)');
let active = 0, phase = 'loading', userPaused = motion.matches;
let lastClip = null, currentClip = null, bag = [], prepared = null;
let remaining = 0, waitElapsed = 0, epoch = 0, lastTick = 0, singlePreview = false;
const history = [];
const canRun = () => !userPaused && !document.hidden;

function nextClip() {
  if (!bag.length) {
    bag = [...manifest.clips];
    for (let i = bag.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [bag[i], bag[j]] = [bag[j], bag[i]];
    }
  }
  if (bag[0].id === lastClip && bag.length > 1) [bag[0], bag[1]] = [bag[1], bag[0]];
  // A manual preview may have consumed the last remaining identity out of order.
  if (bag.length === 1 && bag[0].id === lastClip) { bag = []; return nextClip(); }
  return bag.shift();
}

function load(video, clip) {
  if (video.cancelLoad) video.cancelLoad();
  const ready = new Promise((resolve, reject) => {
    const finish = (err) => {
      clearTimeout(timer);
      video.removeEventListener('loadeddata', loaded);
      video.removeEventListener('error', failed);
      video.cancelLoad = null;
      err ? reject(err) : resolve();
    };
    const loaded = () => finish();
    const failed = () => finish(new Error('Could not load ' + clip.name));
    const timer = setTimeout(failed, 15000);
    video.cancelLoad = () => finish(new Error('Superseded'));
    video.addEventListener('loadeddata', loaded, {once:true});
    video.addEventListener('error', failed, {once:true});
    video.pause();
    video.muted = true; video.loop = false; video.playsInline = true;
    video.poster = new URL(manifest.poster, root).href;
    video.src = new URL(video.canPlayType('video/webm; codecs="vp9"') ? clip.webm : clip.mp4, root).href;
    video.load();
  });
  ready.catch(() => {}); // The matching start operation handles errors; canceled preloads are expected.
  return ready;
}

function prepare(clip) {
  const index = 1 - active;
  prepared = {clip, index, ready:load(slots[index], clip)};
}

function setPhase(value) {
  phase = value;
  document.querySelector('#stage').dataset.phase = value;
  toggle.textContent = userPaused ? 'Resume' : 'Pause';
  status.textContent = value === 'playing' ? currentClip.name : value === 'starting' ? 'Getting ready' : 'Resting in the neutral pose';
}

function rest() {
  remaining = manifest.wait_min_seconds + Math.random() * (manifest.wait_max_seconds - manifest.wait_min_seconds);
  waitElapsed = 0;
  prepare(nextClip());
  setPhase('waiting');
}

async function start(manual=false) {
  const ticket = ++epoch;
  const incoming = prepared;
  const elapsedRest = waitElapsed;
  setPhase('starting');
  try {
    await incoming.ready;
    if (ticket !== epoch) return;
    if (!canRun()) { remaining=0; setPhase('waiting'); return; }
    const video = slots[incoming.index];
    const firstFrame = 'requestVideoFrameCallback' in video
      ? new Promise(resolve => video.requestVideoFrameCallback(resolve))
      : new Promise(resolve => video.addEventListener('playing', resolve, {once:true}));
    await video.play();
    await firstFrame;
    if (ticket !== epoch) return;
    if (!canRun()) { video.pause(); remaining=0; setPhase('waiting'); return; }
    slots[active].pause();
    slots[active].classList.remove('active');
    active = incoming.index;
    video.classList.add('active');
    currentClip = incoming.clip;
    setPhase('playing');
    history.unshift({id:currentClip.id,name:currentClip.name,rest:elapsedRest,manual});
    history.splice(6);
    historyList.replaceChildren(...history.map(item => {
      const li = document.createElement('li');
      li.textContent = `${item.name} · ${item.manual ? 'selected preview' : 'after ' + item.rest.toFixed(1) + 's rest'}`;
      li.dataset.clip = item.id; li.dataset.rest = item.rest.toFixed(3); li.dataset.manual = String(item.manual);
      return li;
    }));
  } catch (error) {
    if (ticket !== epoch) return;
    if (!canRun()) { remaining=0; setPhase('waiting'); return; }
    userPaused = true;
    errorLabel.textContent = error.message + '. The last frame has been kept on screen.';
    setPhase('waiting');
  }
}

for (const [index, video] of slots.entries()) {
  video.addEventListener('ended', () => {
    if (index !== active || phase !== 'playing') return;
    lastClip = currentClip.id;
    if (singlePreview) { userPaused=true; singlePreview=false; }
    rest();
  });
}

function syncPlayback() {
  if (!canRun()) slots.forEach(video => video.pause());
  else if (phase === 'playing') slots[active].play().catch(() => {userPaused=true; syncPlayback()});
  toggle.textContent = userPaused ? 'Resume' : 'Pause';
}
toggle.addEventListener('click', () => {userPaused=!userPaused; syncPlayback()});
document.addEventListener('visibilitychange', () => {lastTick=performance.now(); syncPlayback()});
motion.addEventListener('change', event => {if (event.matches) {userPaused=true; syncPlayback()}});

for (const button of document.querySelectorAll('[data-play]')) button.addEventListener('click', () => {
  ++epoch;
  slots.forEach(video => video.pause());
  userPaused = false; singlePreview = motion.matches;
  prepare(manifest.clips.find(clip => clip.id === button.dataset.play));
  start(true);
});
for (const shape of ['circle','square']) document.querySelector('#'+shape).addEventListener('click', () => {
  document.body.classList.toggle('square', shape === 'square');
  for (const value of ['circle','square']) document.querySelector('#'+value).setAttribute('aria-pressed', String(value === shape));
});

function tick(now) {
  const dt = lastTick ? Math.min((now-lastTick)/1000,.25) : 0;
  lastTick = now;
  if (phase === 'waiting' && canRun()) {
    remaining -= dt; waitElapsed += dt;
    if (remaining <= 0) start();
  }
  countdown.textContent = userPaused ? 'Paused' : phase === 'waiting' ? `Next reaction in ${Math.max(0,remaining).toFixed(1)}s` : phase === 'playing' ? `${Math.min(slots[active].currentTime,currentClip.duration).toFixed(1)} / ${currentClip.duration}s` : 'Loading';
  const source = slots[active];
  if (source.readyState >= 2) for (const canvas of canvases) {
    const ratio = Math.min(devicePixelRatio || 1,2);
    const size = Number(canvas.dataset.size);
    if (canvas.width !== size*ratio) canvas.width=canvas.height=size*ratio;
    canvas.getContext('2d').drawImage(source,0,0,canvas.width,canvas.height);
  }
  requestAnimationFrame(tick);
}

try {
  await load(slots[0], manifest.clips[0]);
  slots[0].classList.add('active');
  rest();
  requestAnimationFrame(tick);
} catch (error) {errorLabel.textContent=error.message; status.textContent='Still image fallback';}
