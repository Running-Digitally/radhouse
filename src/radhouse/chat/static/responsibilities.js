const $ = selector => document.querySelector(selector);
let csrf = '', active = false;

async function request(path, body) {
  const response = await fetch(path, {credentials:'same-origin',
    ...(body ? {method:'POST', headers:{'Content-Type':'application/json','X-Radhouse-CSRF':csrf}, body:JSON.stringify(body)} : {})});
  if(response.status === 401) { location.assign('/'); throw new Error('Please sign in again.'); }
  if(!response.ok) throw new Error(body?'This change could not be saved. Please try again.':'Responsibilities could not be loaded. They may not be enabled on this server.');
  return response.json();
}
function text(tag, content, className) {
  const node = document.createElement(tag); node.textContent = content;
  if(className) node.className = className;
  return node;
}
function showError(error) { $('#error').textContent=error.message; $('#error').hidden=false; }
function showCoverage(value) {
  const last=value.last_review;
  const states={quiet:'Checked; nothing needs your attention.', ready:'Suggestions or follow-up preparation ready.', running:'Review in progress.',
    failed:'The last review failed.', interrupted:'The last review was interrupted.', stale:'New conversation arrived; a fresh review is needed.',
    revoked:'The earlier review was stopped by a scope change.'};
  const coverage=value.coverage;
  const stale=active && (!coverage || Date.now()/1000-coverage.checked_at>7200);
  let summary='No completed review yet.';
  if(last) {
    const detail=last.error==='review_evidence_too_large'?'Review input exceeded the size limit; shorten progress notes.':states[last.state]||'Review status unavailable.';
    summary=detail+' '+new Date(last.created_at*1000).toLocaleString();
  }
  $('#coverage').textContent=(active?'Permission enabled. ':'Paused. ')+
    (stale?'Recent coverage has not been established. ':'')+
    (coverage?.outcome==='budget_wait'?'Waiting for the review budget to renew. ':'')+
    summary;
}
function actionButton(label, item, body, secondary = false, disabled = false) {
  const button=text('button',label,secondary?'secondary':''); button.disabled=disabled;
  button.addEventListener('click',async()=>{button.disabled=true;try {
    await request('/chat/responsibilities/commitments/'+encodeURIComponent(item.id),typeof body==='function'?body():body);
    $('#error').hidden=true; await refresh();
  }catch(error){showError(error);button.disabled=false;}});
  return button;
}
function researchCard(card, item, live) {
  const research=item.followup.research;
  if(!research) return;
  let status=research.enabled?'Enabled for this commitment.':'Off for this commitment.';
  if(research.enabled&&!live) status='Research is inactive because this follow-up has ended.';
  card.append(text('h4','Public-web research'),text('p',status,'badge'));
  const coverage=research.coverage;
  if(coverage) card.append(text('p',
    (coverage.coverage==='unavailable'?'Sources could not be checked.':'Limited research: '+coverage.source_count+' source(s) checked.')+
    ' '+new Date(coverage.checked_at*1000).toLocaleString()+'. Search does not cover the whole web.','muted'));
  else if(research.enabled&&live) card.append(text('p','Awaiting its first public-web check.','muted'));
  if(!live) return;
  const label=text('label','Public research question');label.htmlFor='research-'+item.id;
  const question=document.createElement('textarea');question.id=label.htmlFor;question.rows=2;question.maxLength=300;
  question.value=research.question;question.placeholder='A public question that would help this commitment';
  const disclosure=text('small','Only this question is sent to Keenable for search. Leave out private details. Radhouse reads up to two public pages; it cannot use your browser logins or act on the results.');
  const actions=document.createElement('div');actions.className='actions';
  actions.append(actionButton(research.enabled?'Update public question':'Enable public research',item,
    ()=>({action:'research',revision:item.followup.revision,question:question.value}),false,!active));
  if(research.enabled) actions.append(actionButton('Stop public research',item,
    {action:'research',revision:item.followup.revision,question:''},true));
  card.append(label,question,disclosure,actions);
}
function citations(card, note) {
  for(const citation of note.citations||[]) {
    const url=new URL(citation.url);
    if(url.protocol!=='https:' || url.username || url.password) continue;
    const link=document.createElement('a');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';
    link.textContent=citation.title;
    const source=document.createElement('aside');source.append(link,text('blockquote',citation.quote),
      text('small','Checked '+new Date(citation.retrieved_at*1000).toLocaleString()));card.append(source);
  }
}
function followupCard(card, item) {
  const followup=item.followup;
  if(!followup) return;
  card.append(text('h4','Ongoing follow-up'),text('p',followup.state,'badge'));
  const live=['active','snoozed'].includes(followup.state);
  if(live) card.append(text('p','Next review: '+new Date(followup.next_review_at*1000).toLocaleString()+
    '. Checks may wait for the shared review budget.','muted'));
  card.append(text('p',followup.last_review_at?'Last reviewed: '+new Date(followup.last_review_at*1000).toLocaleString():'Awaiting its first follow-up review.','muted'));
  if(followup.latest_note) {
    const note=followup.latest_note;
    card.append(text('h4',note.action==='completion_check'?'Does this mean it is complete?':'Latest preparation'),
      text('p',note.reason),text('p',note.preparation),text('blockquote',note.quote));
    citations(card,note);
  }
  researchCard(card,item,live);
  if(!live) return;
  const label=text('label','Progress or a correction'); label.htmlFor='progress-'+item.id;
  const progress=document.createElement('textarea');progress.id=label.htmlFor;progress.rows=3;progress.maxLength=2000;
  progress.value=followup.progress;progress.placeholder='What has changed?';
  const controls=document.createElement('div');controls.className='actions';
  const body=action=>({action,revision:followup.revision});
  controls.append(actionButton('Save progress',item,()=>({...body('progress'),progress:progress.value}),false,!active),
    actionButton('Snooze 1 day',item,{...body('snooze'),days:1},true,!active),
    actionButton('Snooze 1 week',item,{...body('snooze'),days:7},true,!active));
  if(followup.state==='snoozed') controls.append(actionButton('Resume now',item,body('resume'),false,!active));
  controls.append(actionButton('Mark complete',item,body('complete')),
    actionButton('Stop following up',item,body('stop'),true));
  card.append(label,progress,controls);
}
function renderItem(item) {
  const card=document.createElement('article');card.id='commitment-'+item.id;
  card.append(text('span',item.state==='suggested'?'For your confirmation':item.state,'badge'),text('h3',item.title),
    text('blockquote',item.quote),text('p',item.reason),text('h4','A possible next step'),text('p',item.preparation));
  const source=document.createElement('a');source.href='/?request='+encodeURIComponent(item.source_request_id);
  source.textContent='Return to the conversation';card.append(source);
  if(item.state==='suggested') {
    const actions=document.createElement('div');actions.className='actions';
    actions.append(actionButton('Confirm and follow up',item,{decision:'confirmed_followup'},false,!active),
      actionButton('Not a commitment',item,{decision:'dismissed'},true));
    card.append(actions,text('small','Confirmation starts private ongoing review. Radhouse can prepare next steps and ask about progress; you control snooze, completion and stop. No external action is authorized.'));
  } else if(item.state==='confirmed' && !item.followup) {
    card.append(text('p','Saved only. Ongoing follow-up has not been started.'),
      actionButton('Start follow-up',item,{decision:'confirmed_followup'},false,!active));
  }
  followupCard(card,item);
  return card;
}
async function refresh() {
  const value=await request('/chat/responsibilities/commitments');active=value.active;
  $('#toggle').textContent=active?'Pause':'Resume reviews';$('#toggle').disabled=false;
  $('#sources').textContent=value.scope.sources;
  $('#preparation').textContent=value.scope.preparation+'. '+value.scope.confirmation+'.';
  $('#excluded').textContent='Outside this scope: '+value.scope.excluded+'. Up to ten active commitments, four reviews and two new notifications per day. Check-ins become eligible after one day; unanswered check-ins back off to three days, then weekly.';
  showCoverage(value);
  $('#suggestions').replaceChildren();$('#empty').hidden=value.suggestions.length>0;
  for(const item of value.suggestions) $('#suggestions').append(renderItem(item));
}
$('#toggle').addEventListener('click',async()=>{ $('#toggle').disabled=true;try {
  await request('/chat/responsibilities/commitments',{active:!active});await refresh();
}catch(error){showError(error);$('#toggle').disabled=false;}});
try {const session=await request('/auth/session');csrf=session.csrf_token;await refresh();}
catch(error){showError(error);$('#toggle').textContent='Not available yet';}
