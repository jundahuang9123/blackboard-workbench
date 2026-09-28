'use strict';
const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pretty = x => esc(JSON.stringify(x, null, 2));
const state = {config:null, runs:[], run:null, item:null, tab:'assessments', jobs:[], pending:false};
let noticeTimer;
function notice(message, error=false) { clearTimeout(noticeTimer); $('#notice').textContent=message; $('#notice').className=error?'error':''; if(!error) noticeTimer=setTimeout(()=>$('#notice').textContent='',8000); }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Workbench-Token':state.config.token},body:JSON.stringify(body)});
  const value = await response.json();
  if(!response.ok) throw new Error(value.error || 'Request failed.');
  return value;
}
async function action(fn) { if(state.pending) return; state.pending=true; try { await fn(); } catch(e) { notice(e.message,true); } finally { state.pending=false; } }
function selectedItem() { return state.run?.items.find(x=>x.id===state.item); }
function author() { try {return localStorage.getItem('blackboard-reviewer') || '';} catch {return '';} }
function saveAuthor(name) { try {localStorage.setItem('blackboard-reviewer',name);} catch {} }
function date(text) { return new Date(text).toLocaleString(); }
function badge(status) {return `<span class="badge ${esc(status)}">${esc(status.replaceAll('_',' '))}</span>`;}
function llm() { return state.config?.llm || {}; }
function providerById(id) { return (llm().providers || []).find(p=>p.id===id); }
function selectedProvider() { return providerById($('#llm-provider').value); }
function profileFor(id) { return llm().profiles?.[id] || (llm().provider===id?llm():{}); }
function providerLabel(id) { return providerById(id)?.label || id || 'No provider'; }
function environmentKey(profile) { return ['environment','env'].includes(profile.key_source); }
function keyDescription(profile,provider) {
  if(profile.has_key) {
    if(environmentKey(profile)) return 'Using a key from the server environment. It cannot be removed here.';
    if(profile.remembered || ['saved','file','remembered'].includes(profile.key_source)) return 'A key is saved in a protected local file. Its contents are never shown here.';
    return 'A key is available for this server session. It will be removed when the server restarts.';
  }
  return provider?.requires_key?'No key configured. Enter your provider key and save the settings.':'No API key required for this local connection.';
}
function showSettings(open) {
  $('#model-settings').hidden=!open;
  $('#open-settings').setAttribute('aria-expanded',String(open));
  if(open) { $('#model-settings').scrollIntoView({behavior:'smooth',block:'start'}); $('#llm-provider').focus({preventScroll:true}); }
}
function renderProviderProfile() {
  const provider=selectedProvider(); if(!provider)return;
  const profile=profileFor(provider.id);
  $('#llm-models').innerHTML=(provider.models || []).map(m=>`<option value="${esc(m.id)}" label="${esc(m.label||m.id)}"></option>`).join('');
  $('#llm-model').value=profile.model || provider.models?.[0]?.id || '';
  $('#llm-endpoint').value=profile.endpoint || provider.default_endpoint || '';
  $('#llm-endpoint').readOnly=provider.kind!=='local';
  $('#endpoint-label').hidden=provider.kind!=='local';
  $('#endpoint-help').hidden=provider.kind!=='local';
  $('#load-models').hidden=provider.kind!=='local';
  $('#provider-help').textContent=provider.help || 'Choose a suggested model or enter a model identifier supported by your provider.';
  $('#llm-key').value='';
  $('#key-label').firstChild.textContent=provider.requires_key?'API key':'API key (optional)';
  $('#key-status').textContent=keyDescription(profile,provider);
  $('#remember-key').checked=!!profile.remembered;
  $('#remember-key').disabled=false;
  $('#remove-key').hidden=!profile.has_key || environmentKey(profile);
  $('#remove-key').textContent=profile.remembered?'Remove saved key':'Remove session key';
  $('#connection-status').textContent='';
}
function renderSettings() {
  const current=llm();
  $('#llm-provider').innerHTML=(current.providers||[]).map(p=>`<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('');
  $('#llm-provider').value=current.provider || current.providers?.[0]?.id || '';
  renderProviderProfile();
  updateExecution();
}
function modelDescription() { return `${providerLabel(llm().provider)} · ${llm().model||'Choose a model'}`; }
function executionIssue() {
  if(!state.config?.configured) return 'Saved runs and human reviews are ready. The upstream pipeline connection is not configured.';
  if(!llm().ready) return 'Open Model settings, choose a model connection and save it before starting a run.';
  return '';
}
function updateExecution() {
  const current=llm(), provider=providerById(current.provider);
  $('#model-summary').textContent=current.ready?`${modelDescription()} · Configured`:'Model connection needs setup';
  $('#pipeline-model').textContent=`Saved connection: ${modelDescription()}`;
  $('#pipeline-cost').textContent=provider?.kind==='local'?'Runs use your local model server.':'Cloud runs make model requests that may incur provider charges.';
  $('#setup-status').textContent=executionIssue() || `Available sample IDs: ${(state.config.samples||[]).join(', ')}.`;
  $('#run-form').querySelectorAll('input,button').forEach(x=>x.disabled=!state.config.configured || !current.ready);
  $('#test-settings').disabled=!current.ready;
  $('#test-help').textContent=`The test uses the saved connection (${modelDescription()}) and makes one short model request. ${provider?.kind==='local'?'Your local model server handles it.':'A cloud provider may charge for it.'}`;
  if($('#agent-model')) $('#agent-model').textContent=`Saved connection: ${modelDescription()}`;
  if($('#agent-status')) $('#agent-status').textContent=executionIssue();
  if($('#agent-submit')) $('#agent-submit').disabled=!state.config.configured || !current.ready || !selectedItem()?.candidates.length;
}
function settingsBody(clearKey=false) {
  const form=$('#settings-form');
  const provider=selectedProvider(), profile=profileFor(provider.id);
  return {provider:provider.id,model:clearKey?(profile.model||form.elements.model.value.trim()):form.elements.model.value.trim(),endpoint:clearKey?(profile.endpoint||provider.default_endpoint||''):form.elements.endpoint.value.trim(),api_key:clearKey?'':form.elements.api_key.value,remember_key:clearKey?false:form.elements.remember_key.checked,clear_key:clearKey};
}
async function saveSettings(clearKey=false) {
  const current=await api('/api/settings',settingsBody(clearKey));
  $('#llm-key').value='';
  state.config.llm=current;
  renderSettings();
  notice(clearKey?'Key removed.':'Model settings saved.');
}
$('#open-settings').onclick=()=>showSettings($('#model-settings').hidden);
$('#close-settings').onclick=()=>{showSettings(false);$('#open-settings').focus();};
$('#llm-provider').onchange=renderProviderProfile;
$('#settings-form').onsubmit=e=>{e.preventDefault();action(()=>saveSettings());};
$('#remove-key').onclick=()=>action(()=>saveSettings(true));
$('#load-models').onclick=()=>action(async()=>{
  const provider=selectedProvider();
  const result=await api('/api/settings/models',{provider:provider.id,endpoint:$('#llm-endpoint').value.trim()});
  const models=result.models || [];
  $('#llm-models').innerHTML=models.map(m=>`<option value="${esc(m.id)}" label="${esc(m.label||m.id)}"></option>`).join('');
  $('#connection-status').textContent=models.length?`${models.length} available models loaded. Choose one in the Model field, then save.`:'This server returned no models. Load a model on the local server, then try again.';
  if(models.length) $('#llm-model').focus();
});
$('#test-settings').onclick=()=>action(async()=>{
  $('#connection-status').textContent='Sending one short request using the saved connection…';
  $('#test-settings').disabled=true;
  try {
    const result=await api('/api/settings/test',{});
    if(!result.ok) throw new Error(result.message || 'Connection test failed.');
    $('#connection-status').textContent=result.message || `Connected to ${providerLabel(result.provider)} · ${result.model}.`;
  } catch(e) { $('#connection-status').textContent=e.message; throw e; }
  finally { $('#test-settings').disabled=!llm().ready; }
});
async function loadRuns() { state.runs=await api('/api/runs'); renderRuns(); }
function renderRuns() {
  $('#runs').innerHTML=state.runs.length ? `<h3 style="margin-top:25px">Saved runs</h3>`+state.runs.map(r=>`<button class="run-button ${r.id===state.run?.id?'active':''}" data-run="${esc(r.id)}">${esc(r.title)}<small>${r.item_count} attributes · ${r.reviewed} reviewed<br>${esc(date(r.created))}</small></button>`).join('') : '<p class="hint">No runs yet. Your imported runs and reviews will be saved locally.</p>';
  $('#runs').querySelectorAll('[data-run]').forEach(b=>b.onclick=()=>action(()=>openRun(b.dataset.run)));
}
async function openRun(id) {
  state.run=await api('/api/runs/'+id);
  if(!state.run.items.some(i=>i.id===state.item)) state.item=state.run.items[0]?.id;
  renderRuns(); renderRun();
}
function renderRun() {
  $('#welcome').hidden=true; $('#workspace').hidden=false;
  $('#run-title').textContent=state.run.title;
  $('#run-origin').textContent=state.run.origin.replaceAll('_',' ');
  $('#run-meta').textContent=`Saved ${date(state.run.created)} · Source hash ${state.run.sha.slice(0,12)}`;
  $('#demo-banner').hidden=!(state.run.raw.workbench_demo || state.run.origin==='synthetic_demo');
  $('#export').href=`/api/runs/${state.run.id}/export`;
  const reviewed=state.run.items.filter(i=>i.status!=='unreviewed').length;
  const failed=state.run.items.filter(i=>!i.candidates.length).length;
  $('#stats').innerHTML=`<div class="stat"><b>${state.run.items.length}</b><span>Attributes in this run</span></div><div class="stat"><b>${reviewed}</b><span>Human-reviewed attributes</span></div><div class="stat"><b>${failed}</b><span>Without validated candidates</span></div>`;
  renderQueue(); renderItem();
}
function renderQueue() {
  if(!state.run) return;
  const query=$('#search').value.toLowerCase(), filter=$('#status-filter').value;
  const items=state.run.items.filter(i=>i.name.toLowerCase().includes(query)&&(!filter||i.status===filter));
  $('#items').innerHTML=items.length?items.map(i=>`<button class="item-button ${i.id===state.item?'active':''}" data-item="${i.id}"><strong>${esc(i.name)}</strong><br>${badge(i.status)}<small>${i.candidates.length} candidates</small></button>`).join(''):'<p class="empty">No matching attributes.</p>';
  $('#items').querySelectorAll('[data-item]').forEach(b=>b.onclick=()=>{state.item=b.dataset.item;renderQueue();renderItem();});
}
function setTab(tab) {
  state.tab=tab;
  document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.tab===tab)));
  document.querySelectorAll('.tab-panel').forEach(p=>p.hidden=p.id!==tab);
}
function signalValues(candidate,item) {
  const values = Object.entries(candidate.record).filter(([k])=>k.endsWith('_vote')).map(([k,v])=>[k.replace(/_vote$/,'').replaceAll('_',' '),v]);
  const row=Array.isArray(item.matrix)?item.matrix.find(x=>x.candidate===candidate.label):null;
  if(!values.length&&row?.agents) return Object.entries(row.agents);
  return values;
}
function renderItem() {
  const item=selectedItem(); if(!item)return;
  $('#item-heading').innerHTML=`<span class="eyebrow">Attribute workspace</span><h2>${esc(item.name)}</h2>${badge(item.status)}<span class="badge">Review version ${item.version}</span>`;
  $('#assessments').innerHTML=`<h3>Original machine selection</h3><pre>${esc(item.machine_mapping?.candidate || 'No final mapping recorded.')}</pre><p class="hint">${esc(item.machine_mapping?.selection_reason || 'No selection rationale recorded.')}</p><h3>Validated candidates</h3><p class="hint">These assessments come from the imported run. “Validated” is not human approval or proof of semantic correctness.</p>`+item.candidates.map((c,n)=>`<article class="candidate"><span class="eyebrow">Candidate ${n+1} · ${c.id.slice(0,6)}</span><h3>${esc(c.label)}</h3><div class="signals">${signalValues(c,item).map(([k,v])=>`<div class="signal"><b>${esc(k)}</b>${typeof v==='object'&&v!==null ? `<span class="badge">${esc(v.accepted===undefined?(v.proximity||v.label||'Recorded'):v.accepted?'Supports':'Does not support')}</span><p>${typeof v.reason==='object'?pretty(v.reason):esc(v.reason||JSON.stringify(v))}</p>`:esc(v)}</div>`).join('')||'<p class="hint">No named signal votes recorded.</p>'}</div><details><summary>Complete candidate record</summary><pre>${pretty(c.record)}</pre></details></article>`).join('')+(item.candidates.length?'':'<div class="callout">No validated candidates. You can record a rejection or request further review; acceptance is unavailable.</div>')+`<details><summary>Original matrix and processing logs</summary><pre>${pretty(item.original)}</pre></details><details><summary>Run-level evaluation and changes</summary><pre>${pretty({evaluation:state.run.raw.evaluation,reasoning_effect:state.run.raw.reasoning_effect})}</pre></details><details><summary>Available source context</summary><pre>${pretty(state.run.raw.workbench_context||{notice:'This export did not include original source data. Recorded assessments are not a substitute for the original documentation.'})}</pre></details>`;
  renderDiscussion(item); renderHistory(item);
  $('#decision-candidate').innerHTML='<option value="">Choose a validated candidate</option>'+item.candidates.map(c=>`<option value="${c.id}">${esc(c.label)}</option>`).join('');
  const selected=item.selected||item.candidates.find(c=>c.label===item.machine_mapping?.candidate)?.id||'';
  $('#decision-candidate').value=selected;
  $('#decision-form').elements.author.value=author();
  $('#decision-form').elements.text.value='';
  $('#decision-form').elements.status.value=item.status==='unreviewed'?(item.candidates.length?'accepted':'needs_review'):item.status;
  setTab(state.tab);
}
function renderDiscussion(item) {
  const original=Object.entries(state.run.raw.discussions||{}).filter(([,d])=>(d.participants||[]).some(p=>(typeof p==='string'?p:p.attribute)===item.name));
  const events=state.run.events.filter(e=>e.item===item.id&&e.kind!=='decision');
  $('#discussion').innerHTML=`<h3>Original council record</h3><p class="hint">Preserved from Sebastian’s export. This is distinct from the human/agent discussion below.</p>`+(original.map(([id,d])=>`<details><summary>${esc(id)} · ${esc(d.conclusion||'No conclusion')}</summary><p>${esc(d.reason)}</p>${(d.turn_logs||[]).map(t=>`<h3>Turn ${esc(t.turn)}</h3>${(t.log||[]).map(post=>`<article class="post"><b>${esc(post.attribute)}</b><p>${esc(post.response)}</p><pre>${pretty({commands:post.commands,parameters:post.command_parameters})}</pre></article>`).join('')}`).join('')}<details><summary>Full original discussion</summary><pre>${pretty(d)}</pre></details></details>`).join('')||'<p class="empty">No original council discussion recorded for this attribute.</p>')+`<h3>Workspace discussion</h3><p class="hint">Posts reference a review version. Replies and decisions persist across reloads.</p>`+(events.map(e=>{const parent=state.run.events.find(p=>p.id===e.parent);return `<article class="post ${e.author_type==='agent'?'agent':''}"><b>${esc(e.author)}</b> ${badge(e.author_type)}<br><small>${esc(date(e.created))} · version ${e.version}${e.model?' · '+esc(e.model):''}</small>${parent?`<blockquote>Reply to ${esc(parent.author)}: ${esc(parent.text.slice(0,180))}</blockquote>`:''}<p>${esc(e.text)}</p>${e.proposed_candidate?`<p><strong>Proposed candidate:</strong> ${esc(item.candidates.find(c=>c.id===e.proposed_candidate)?.label||e.proposed_candidate)}<br><small>Advisory only; human review is required.</small></p>`:''}${e.references?.length?`<p class="hint">Candidate references: ${e.references.map(id=>esc(item.candidates.find(c=>c.id===id)?.label||id)).join('; ')}</p>`:''}<button type="button" class="reply" data-reply="${e.id}">Reply</button></article>`;}).join('')||'<p class="empty">Start the discussion with a question or objection.</p>')+`<form id="comment-form"><div class="form-row"><label>Your name<input name="author" value="${esc(author())}" maxlength="100" required></label><label>Reply to<select name="parent"><option value="">New post</option>${events.map(e=>`<option value="${e.id}">${esc(e.author)}: ${esc(e.text.slice(0,50))}</option>`).join('')}</select></label></div><label>Candidate reference (optional)<select name="reference"><option value="">General comment</option>${item.candidates.map(c=>`<option value="${c.id}">${esc(c.label)}</option>`).join('')}</select></label><label>Question, evidence or objection<textarea name="text" rows="3" required maxlength="10000"></textarea></label><button class="primary" type="submit">Save post</button></form><details><summary>Request bounded agent review</summary><p class="hint">A mapping assessor and challenger read the recorded context and this discussion. One round makes two model calls. They can propose changes; they cannot approve mappings. This is a new review condition, separate from the original SAST run.</p><form id="agent-form"><p id="agent-model" class="saved-model">Saved connection: ${esc(modelDescription())}</p><label>Rounds<select name="rounds"><option value="1">1 round · 2 calls</option><option value="2">2 rounds · 4 calls</option><option value="3">3 rounds · 6 calls</option></select></label><button id="agent-submit" type="submit" ${!state.config.configured||!llm().ready||!item.candidates.length?'disabled':''}>Start agent review</button></form><p id="agent-status" class="hint">${esc(executionIssue())}</p></details>`;
  $('#comment-form').onsubmit=e=>{e.preventDefault();action(async()=>{const form=e.target;const body=Object.fromEntries(new FormData(form));saveAuthor(body.author);body.version=item.version;body.references=body.reference?[body.reference]:[];body.parent=body.parent||null;await submitEvent('comment',body);notice('Post saved.');});};
  document.querySelectorAll('[data-reply]').forEach(b=>b.onclick=()=>{ $('#comment-form').elements.parent.value=b.dataset.reply; $('#comment-form').elements.text.focus(); });
  $('#agent-form').onsubmit=e=>{e.preventDefault();action(async()=>{const values=Object.fromEntries(new FormData(e.target));await api('/api/jobs',{kind:'discussion',run_id:state.run.id,item_id:item.id,version:item.version,rounds:Number(values.rounds)});await loadJobs();notice('Agent review started. Follow execution history below.');});};
}
function renderHistory(item) {
  const decisions=state.run.events.filter(e=>e.item===item.id&&e.kind==='decision');
  $('#history').innerHTML=`<h3>Machine result stays unchanged</h3><pre>${esc(item.machine_mapping?.candidate||'No machine selection')}</pre><h3>Current human decision</h3><p>${badge(item.status)} · version ${item.version}</p><pre>${esc(item.candidates.find(c=>c.id===item.selected)?.label||'No human-accepted mapping')}</pre><h3>Decision history</h3>`+decisions.map(e=>`<article class="history-event"><b>${esc(e.author)}</b> ${badge(e.status)}<p class="hint">${esc(date(e.created))} · version ${e.version} → ${e.new_version}</p><p>${esc(e.text)}</p>${e.selected?`<pre>${esc(item.candidates.find(c=>c.id===e.selected)?.label||e.selected)}</pre>`:''}</article>`).join('')+(decisions.length?'':'<p class="empty">No human decision recorded.</p>');
}
async function submitEvent(kind,body) {state.run=await api(`/api/runs/${state.run.id}/items/${state.item}/${kind}`,body);await loadRuns();renderRun();}
$('#decision-form').onsubmit=e=>{e.preventDefault();action(async()=>{const body=Object.fromEntries(new FormData(e.target));body.version=selectedItem().version;saveAuthor(body.author);await submitEvent('decision',body);notice('Decision saved. The original machine result is unchanged.');});};
$('#demo').onclick=()=>action(async()=>{state.run=await api('/api/demo',{});state.item=state.run.items[0].id;await loadRuns();renderRun();notice('Synthetic example saved to your workspace.');});
$('#import').onchange=e=>action(async()=>{const file=e.target.files[0];if(!file)return;if(file.size>18_000_000)throw new Error('Choose a JSON file smaller than 18 MB.');const raw=JSON.parse(await file.text());state.run=await api('/api/import',{title:file.name.replace(/\.json$/,''),raw});state.item=state.run.items[0].id;await loadRuns();renderRun();e.target.value='';notice('Run imported and saved locally.');});
$('#refresh').onclick=()=>action(async()=>{await loadRuns();if(state.run)await openRun(state.run.id);await loadJobs();notice('Saved records refreshed.');});
$('#search').oninput=renderQueue;$('#status-filter').onchange=renderQueue;
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
$('#run-form').onsubmit=e=>{e.preventDefault();action(async()=>{const values=Object.fromEntries(new FormData(e.target));const ids=x=>x.split(/[\s,]+/).filter(Boolean);await api('/api/jobs',{kind:'pipeline',samples:ids(values.samples),historical:ids(values.historical),timeout:Number(values.timeout)});await loadJobs();notice('SAST run started. You can continue reviewing saved runs.');});};
async function loadJobs() {
  const openLogs=new Set([...$('#jobs').querySelectorAll('details[open]')].map(d=>d.dataset.jobLog));
  const logScroll=new Map([...$('#jobs').querySelectorAll('details[open] pre')].map(p=>[p.closest('details').dataset.jobLog,p.scrollTop]));
  const jobs=await api('/api/jobs');
  const completed=jobs.filter(j=>j.status==='completed'&&state.jobs.some(old=>old.id===j.id&&old.status!=='completed'));
  state.jobs=jobs;
  $('#jobs-section').hidden=!jobs.length;
  $('#jobs').innerHTML=jobs.map(j=>`<article class="job"><h3>${esc(j.kind==='pipeline'?'SAST pipeline':'Bounded agent review')} ${badge(j.status)}</h3><p class="hint">${esc(date(j.created))} · ${j.provider?esc(providerLabel(j.provider))+' · ':''}${esc(j.model)}${j.rounds?' · '+j.rounds+' rounds':''}</p><p>${esc(j.message)}</p>${j.run_ids.map(id=>`<button data-job-run="${id}">Open saved run</button>`).join('')}${j.kind==='discussion'&&j.status==='completed'?`<button data-job-run="${j.run_id}">Refresh run to view responses</button>`:''}${['running','queued'].includes(j.status)?`<button data-cancel="${j.id}">Cancel job</button>`:''}<details data-job-log="${esc(j.id)}" ${openLogs.has(j.id)?'open':''}><summary>Worker log & execution metadata</summary><pre>${esc(j.log||'No log yet.')}</pre><p class="hint">Upstream revision: ${esc(j.upstream_revision)} · Time limit: ${j.timeout}s · Job ${j.id}</p></details></article>`).join('');
  $('#jobs').querySelectorAll('details[open] pre').forEach(p=>{p.scrollTop=logScroll.get(p.closest('details').dataset.jobLog)||0;});
  document.querySelectorAll('[data-cancel]').forEach(b=>b.onclick=()=>action(async()=>{await api(`/api/jobs/${b.dataset.cancel}/cancel`,{});notice('Cancellation requested.');await loadJobs();}));
  document.querySelectorAll('[data-job-run]').forEach(b=>b.onclick=()=>action(async()=>{await loadRuns();await openRun(b.dataset.jobRun);$('#workspace').scrollIntoView({behavior:'smooth'});}));
  if(completed.length){await loadRuns();notice('Model job completed. Open or refresh its run to inspect the saved result.');}
}
async function init() {
  try {state.config=await api('/api/config');renderSettings();if(!llm().ready)showSettings(true);await loadRuns();await loadJobs();}
  catch(e){notice(e.message,true);}
}
init();
setInterval(async()=>{if(!state.config||document.hidden||state.pending)return;try{await loadJobs();}catch{}},4000);
