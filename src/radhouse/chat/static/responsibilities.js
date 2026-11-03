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
async function refresh() {
  const value = await request('/chat/responsibilities/commitments');
  active = value.active;
  $('#toggle').textContent=active?'Pause':'Enable suggestions'; $('#toggle').disabled=false;
  $('#sources').textContent=value.scope.sources;
  $('#preparation').textContent=value.scope.preparation+'. '+value.scope.confirmation+'.';
  $('#excluded').textContent='Outside this scope: '+value.scope.excluded+'. Up to four reviews per day.';
  const last=value.last_review;
  const states={quiet:'Checked; nothing new to suggest.', ready:'Suggestions prepared.', running:'Review in progress.',
    failed:'The last review failed.', interrupted:'The last review was interrupted.', stale:'New conversation arrived; a fresh review is needed.',
    revoked:'The earlier review was stopped by a scope change.'};
  const coverage=value.coverage;
  const stale=active && (!coverage || Date.now()/1000-coverage.checked_at>7200);
  $('#coverage').textContent=(active?'Permission enabled. ':'Paused. ')+
    (stale?'Recent coverage has not been established. ':'')+
    (coverage?.outcome==='budget_wait'?'Waiting for the review budget to renew. ':'')+
    (last?(states[last.state]||'Review status unavailable.')+' '+new Date(last.created_at*1000).toLocaleString():'No completed review yet.');
  $('#suggestions').replaceChildren(); $('#empty').hidden=value.suggestions.length>0;
  for(const item of value.suggestions) {
    const card=document.createElement('article'); card.id='commitment-'+item.id;
    card.append(text('span', item.state==='suggested'?'For your confirmation':item.state,'badge'), text('h3',item.title),
      text('blockquote',item.quote),text('p',item.reason),text('h4','A possible next step'),text('p',item.preparation));
    const source=document.createElement('a'); source.href='/?request='+encodeURIComponent(item.source_request_id);
    source.textContent='Return to the conversation'; card.append(source);
    if(item.state==='suggested') {
      const actions=document.createElement('div');actions.className='actions';
      for(const [label,decision] of [['Confirm commitment','confirmed'],['Not a commitment','dismissed']]) {
        const button=text('button',label,decision==='dismissed'?'secondary':'');
        button.addEventListener('click',async()=>{button.disabled=true;try {
          await request('/chat/responsibilities/commitments/'+encodeURIComponent(item.id),{decision}); await refresh();
        }catch(error){showError(error);button.disabled=false;}});actions.append(button);
      }
      card.append(actions,text('small','Confirmation saves this commitment. It does not schedule follow-ups or authorize external actions.'));
    }
    $('#suggestions').append(card);
  }
}
$('#toggle').addEventListener('click',async()=>{ $('#toggle').disabled=true;try {
  await request('/chat/responsibilities/commitments',{active:!active});await refresh();
}catch(error){showError(error);$('#toggle').disabled=false;}});
try {const session=await request('/auth/session');csrf=session.csrf_token;await refresh();}
catch(error){showError(error);$('#toggle').textContent='Not available yet';}
