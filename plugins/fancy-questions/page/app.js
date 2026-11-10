(function(){
'use strict';
/* Data is injected by `qw build` (normalized and checked there). */
const DATA = /*QW_DATA*/null;
const PAGE = DATA.page, Q = DATA.cards, SECTIONS = PAGE.sections, TOTAL = Q.length;
const parts = q => [q].concat(q.parts || []);
const ALLQ = Q.flatMap(parts);

/* ---------- state ---------- */
const answers = {}, pending = {};
let idx = 0, mode = '';
let db = null, user = null, meId = null;
const LS = 'qw-' + PAGE.slug + '-answers-v1', LSPOS = 'qw-' + PAGE.slug + '-pos-v1';
try{ const raw=localStorage.getItem(LS); if(raw) Object.assign(answers, JSON.parse(raw)); const p=parseInt(localStorage.getItem(LSPOS)||'0',10); if(p>=0&&p<=TOTAL+1) idx=p; }catch(e){}
function persistLocal(){ try{ localStorage.setItem(LS, JSON.stringify(answers)); localStorage.setItem(LSPOS,String(idx)); }catch(e){} }

const $ = id => document.getElementById(id);
const stage=$('stage'), bar=$('bar'), fill=$('fill'), chips=$('chips'), saveEl=$('save'), saveTxt=$('savetxt'), toastEl=$('toast');
let toastT; function toast(msg){ toastEl.textContent=msg; toastEl.classList.add('show'); clearTimeout(toastT); toastT=setTimeout(()=>toastEl.classList.remove('show'),2200); }
function setSave(state,text){ saveEl.className='save '+state; saveTxt.textContent=text; }
function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
const done1 = x => !!(answers[x.id] && answers[x.id].optionId);
const isDone = q => parts(q).every(done1);
const anyDone = q => parts(q).some(done1);
const answered = () => Q.filter(isDone).length;
const optOf = (q, a) => a && a.optionId ? q.options.find(o => o.id === a.optionId) : null;
const secName = k => (SECTIONS.find(s => s.id === k) || {label: k}).label;
const ext = (url, label) => `<a href="${esc(url)}" target="_blank" rel="noopener">${label}</a>`;

/* ---------- visuals ---------- */
const TONE = {yes:'var(--yes)', no:'var(--no)', discuss:'var(--discuss)', muted:'var(--p3)', accent:'var(--accent)'};
const V = {
  bars(v){
    const items=v.rows, W=380, rowH=30, pad=v.pad||132, room=v.room||92, H=items.length*rowH+6;
    const max=v.max||Math.max(...items.map(i=>i.value),1), scale=(W-pad-room)/max;
    let s=`<svg class="bar-grow" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(items.map(i=>i.label+' '+(i.text||i.value)).join('; '))}">`;
    items.forEach((it,i)=>{ const y=i*rowH+4, w=Math.max(2,it.value*scale);
      s+=`<text class="l" x="${it.indent?12:0}" y="${y+15}" style="font-size:13px">${esc(it.label)}</text>`;
      s+=`<rect class="g" x="${pad}" y="${y}" width="${w}" height="20" rx="4" fill="${TONE[it.tone]||TONE.accent}" style="transition-delay:${i*0.12}s"/>`;
      s+=`<text x="${pad+w+6}" y="${y+15}" style="font-size:13px">${esc(it.text!=null?it.text:it.value)}</text>`; });
    return s+'</svg>';
  },
  split(v){
    const tot=v.parts.reduce((a,p)=>a+p.value,0)||1;
    return `<div class="qv-split"><div class="qv-split-bar" role="img" aria-label="${esc(v.parts.map(p=>p.label+' '+p.value).join('; '))}">${v.parts.map(p=>`<i style="--w:${(p.value/tot*100).toFixed(1)}%;background:${TONE[p.tone]||TONE.accent}"></i>`).join('')}</div><div class="qv-legend">${v.parts.map(p=>`<span><i style="background:${TONE[p.tone]||TONE.accent}"></i><b class="num">${esc(p.text!=null?p.text:p.value)}</b> ${esc(p.label)}</span>`).join('')}</div></div>`;
  },
  flow(v){
    return `<ol class="qv-flow">${v.steps.map(s=>`<li class="t-${esc(s.tone||'accent')}"><b>${esc(s.label)}</b>${s.note?`<span>${esc(s.note)}</span>`:''}</li>`).join('')}</ol>`;
  },
  tree(v){
    const node = n => typeof n === 'string' || !n.ask
      ? `<div class="qv-leaf t-${esc(n.tone||'accent')}">${esc(n.label||n)}</div>`
      : `<div class="qv-ask">${esc(n.ask)}</div><ul>${(n.branches||[]).map(b=>`<li><span class="qv-br">${esc(b.when)}</span>${node(b.then)}</li>`).join('')}</ul>`;
    return `<div class="qv-tree">${node(v.root)}</div>`;
  },
  beforeAfter(v){
    const col = (c, cls) => `<div class="qv-col ${cls}"><div class="qv-h">${esc(c.label)}</div><ul>${c.lines.map(l=>`<li class="t-${esc(l.tone||'')}">${esc(l.text||l)}</li>`).join('')}</ul></div>`;
    return `<div class="qv-ba">${col(v.before,'before')}<div class="qv-arrow" aria-hidden="true">→</div>${col(v.after,'after')}</div>`;
  },
  steps(v){
    return `<ol class="qv-steps">${v.items.map(s=>`<li class="t-${esc(s.tone||'accent')}"><span class="num">${esc(s.when||'')}</span><b>${esc(s.label)}</b>${s.note?`<span>${esc(s.note)}</span>`:''}</li>`).join('')}</ol>`;
  },
  table(v){
    return `<div class="qv-table"><table><thead><tr>${v.cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${v.rows.map((r,i)=>`<tr${(v.highlight||[]).includes(i)?' class="hl-row"':''}>${r.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  },
  image(v){ return `<img class="qv-img" src="${esc(v.src)}" alt="${esc(v.alt)}" loading="lazy">`; },
  pair(v){ return `<div class="two side">${visual(v.a)}${visual(v.b)}</div>`; },
  svg(v){ return v.svg; },
  stack(v){ return `<div class="two">${v.items.map(visual).join('')}</div>`; }
};
const visual = v => v && V[v.kind] ? V[v.kind](v) : '';

/* ---------- rendering ---------- */
function render(dir){
  const old=stage.querySelector('.screen:not(.leaving)');
  if(old){ old.classList.add('leaving'); setTimeout(()=>old.remove(),320); }
  const el=document.createElement('section'); el.className='screen'+(dir<0?' back':'');
  el.innerHTML = idx===0 ? openingHTML() : idx>TOTAL ? summaryHTML() : questionHTML(Q[idx-1]);
  stage.appendChild(el);
  requestAnimationFrame(()=>requestAnimationFrame(()=>el.classList.add('ready')));
  wire(el); bar.hidden = idx===0; updateBar(); persistLocal();
  if(idx===0) runCounters(el);
  if(idx>TOTAL) fillSummary(el);
  window.scrollTo({top:0,behavior:'smooth'});
  const h=el.querySelector('h1,h2'); if(h){h.setAttribute('tabindex','-1'); h.focus({preventScroll:true});}
}
function updateBar(){
  const pct = idx===0?0: idx>TOTAL?100 : Math.round(answered()/TOTAL*100);
  fill.style.width=pct+'%';
  const cur = idx>=1&&idx<=TOTAL ? Q[idx-1].section : null;
  chips.innerHTML = (SECTIONS.length>1 ? SECTIONS.map(s=>{
    const qs=Q.filter(q=>q.section===s.id); if(!qs.length) return '';
    const d=qs.filter(isDone).length;
    return `<button type="button" class="chip${cur===s.id?' on':''}${d===qs.length?' done':''}" data-sec="${esc(s.id)}">${esc(s.label)} <span class="num">${d}/${qs.length}</span></button>`;
  }).join('') : `<span class="chip on">Question <span class="num">${Math.min(idx,TOTAL)}/${TOTAL}</span></span>`) + (idx>TOTAL?'<span class="chip on">Summary</span>':'');
  chips.querySelectorAll('[data-sec]').forEach(b=>b.addEventListener('click',()=>{
    const qs=Q.map((q,i)=>[q,i]).filter(([q])=>q.section===b.dataset.sec);
    const t=(qs.find(([q])=>!isDone(q))||qs[0]); go(t[1]+1); }));
}
function minutes(n){ return Math.max(1, Math.round(n*(PAGE.minutesPerCard||0.75))); }
function openingHTML(){
  const done=answered(), left=TOTAL-done, compact=TOTAL<=3;
  const urgent=Q.filter(q=>q.urgent&&!isDone(q)).length;
  const lr=PAGE.lastRound;
  const head = PAGE.heading || `${PAGE.audience?esc(PAGE.audience)+', ':''}${left?plural(left,'question')+(done?' left':''):'all done'}.${left?' About '+plural(minutes(left),'minute')+'.':''}`;
  const stats=(PAGE.stats||[]).map(s=>`<div class="stat"><span class="big num" data-count="${+s.value}">0</span><span class="what">${esc(s.what)}</span><span class="how">${esc(s.how||'')}</span></div>`).join('');
  const total=lr&&lr.decided?lr.decided+TOTAL:0;
  return `
  <div class="eyebrow"><span class="tick">${esc(PAGE.eyebrow||PAGE.title)}</span>${lr&&lr.url?`<span>·</span>${ext(lr.url, esc(lr.label||'last round'))}`:''}</div>
  <h1>${head}</h1>
  ${PAGE.lead?`<p class="lead">${esc(PAGE.lead)}</p>`:''}
  ${compact?'':`<div class="stats">${stats}
    <div class="stat you"><span class="big num" data-count="${left}">0</span><span class="what">need your answer</span><span class="how">${done?`<b>${done} done</b>`:''}${done&&urgent?' · ':''}${urgent?plural(urgent,'urgent one'):''}</span></div>
  </div>`}
  ${total?`<div class="split" aria-hidden="true"><i class="done" style="--w:${(lr.decided/total*100).toFixed(1)}%"></i><i class="you" style="--w:${(TOTAL/total*100).toFixed(1)}%"></i></div>
  <div class="legend"><span><b>${lr.decided}</b> ${esc(lr.decidedLabel||'decided')}</span><span><b>${TOTAL}</b> for you</span></div>`:''}
  ${compact?'':`<ol class="cards7">
    ${Q.map((q,i)=>{const d=isDone(q); return `<li class="${d?'done':''}" style="animation-delay:${Math.min(.6+i*.08,2)}s" data-go="${i+1}" tabindex="0" role="link"><span class="n">${d?'✓':i+1}</span><span>${SECTIONS.length>1?`<b>${esc(secName(q.section))}:</b> `:''}${esc(q.short)}${q.parts&&q.parts.length?` <span class="num" style="font-size:12px;color:var(--muted)">(${q.parts.length+1} parts)</span>`:''}${q.badge?` <span class="badge">${esc(q.badge)}</span>`:''}</span></li>`;}).join('')}
  </ol>`}
  <p class="whyline">${esc(PAGE.whyline||'The recommended answer is marked on each screen. “Let’s discuss” parks a question for a call. The text box under each question is always there for your own words.')}</p>
  <div class="nav"><span class="hint" style="margin:0"><kbd>1</kbd>–<kbd>4</kbd> pick · <kbd>→</kbd> next · <kbd>←</kbd> back</span>
    <span style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">${urgent&&TOTAL>8?`<button class="btn" id="urgent">Urgent first (${urgent}) →</button>`:''}<button class="btn primary" data-go="${done&&left?Q.findIndex(q=>!isDone(q))+1:1}">${done?'Continue':'Start'} →</button></span></div>`;
}
function nextLabel(q){
  if(isDone(q)) return idx===TOTAL?'See summary →':'Next →';
  if(anyDone(q)) return 'Part '+(parts(q).findIndex(x=>!done1(x))+1)+' still open ↓';
  return 'Skip for now →';
}
function questionHTML(q){
  const n=Q.indexOf(q)+1, ps=parts(q);
  const tick=q.tickets.map(t=>t.url?`<a class="tick" href="${esc(t.url)}" target="_blank" rel="noopener">${esc(t.label||t.id)}</a>`:`<span class="tick">${esc(t.label||t.id)}</span>`).join(', ');
  return `
  <div class="eyebrow"><span>Question <span class="num">${n}</span> of <span class="num">${TOTAL}</span></span>${SECTIONS.length>1?`<span>·</span><span>${esc(secName(q.section))}</span>`:''}${tick?`<span>·</span>${tick}`:''}${q.badge?`<span class="badge">${esc(q.badge)}</span>`:''}</div>
  ${ps.map((x,p)=>(p?`<div class="partsep">Part ${p+1} of ${ps.length}</div>`:'')+blockHTML(x,p)).join('')}
  <div class="nav">
    <button class="btn ghost" data-go="${idx-1}">← Back</button>
    <button class="btn ${isDone(q)?'primary':''}" id="next">${nextLabel(q)}</button>
  </div>
  <p class="hint"><kbd>1</kbd>–<kbd>${Math.min(9,q.options.length)}</kbd> pick${ps.length>1?' (keys set part 1)':''} · <kbd>→</kbd> next · <kbd>←</kbd> back · <kbd>Esc</kbd> overview</p>`;
}
function picksHTML(q,o,i,a,p){
  const pk=o.picks, sel=(a.optionId===o.id||pending[q.id]===i), on=sel?(a.picks||[]):[];
  const item = it => { const v=it.value||it, lbl=it.label||v;
    return pk.groups
      ? `<label class="urow"><span class="m">${esc(lbl)}</span><span class="z">${esc(it.detail||'')}</span><input type="checkbox" class="sw" data-pick="${i}" value="${esc(v)}" aria-label="${esc(lbl)}" ${on.includes(v)?'checked':''}></label>`
      : `<label><input type="checkbox" data-pick="${i}" value="${esc(v)}" ${on.includes(v)?'checked':''}>${esc(lbl)}${it.detail?` <span class="z">${esc(it.detail)}</span>`:''}</label>`; };
  const body = pk.groups
    ? `<div class="units">${pk.groups.map(g=>{const c=g.items.filter(it=>on.includes(it.value||it)).length;
        return `<details${c?' open':''}><summary><span>${esc(g.name)}</span><span class="cnt${c?' on':''}">${c?c+' on · ':''}${g.items.length}</span></summary>${g.items.map(item).join('')}</details>`;}).join('')}</div>`
    : `<div class="checks">${pk.items.map(item).join('')}</div>`;
  const short = pending[q.id]===i && on.length<pk.min;
  return `<div data-for="${i}" ${pk.always||sel?'':'hidden'}><label>${esc(pk.label)}</label>${body}<span class="uhint pickmsg${short?' warn':''}">${short?`Tick at least ${pk.min} to save this answer.`:esc(pk.hint||'')}</span></div>`;
}
function blockHTML(q,p){
  const a=answers[q.id]||{};
  const facts=(q.facts||[]).filter(f=>!f.verified);
  return `<div class="part" data-part="${p}">
  <h2>${esc(q.question)}</h2>
  <p class="recline"><b>We recommend:</b> ${esc(q.recommend)}</p>
  ${q.today?`<p class="today"><span class="lbl">${esc(q.today.label||'Today')}</span>${esc(q.today.text)}</p>`:''}
  ${q.after?`<p class="today"><span class="lbl">${esc(q.after.label||'After')}</span>${esc(q.after.text)}</p>`:''}
  <figure class="figure">${visual(q.visual)}<figcaption>${q.example?`<span class="lbl">Worked example</span>${esc(q.example)}`:''}${facts.map(f=>`<span class="ex ph">${esc(f.text)}</span>`).join('')}${q.links&&q.links.length?`<span class="links">${q.links.map(l=>`<a class="hub" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} <span aria-hidden="true">↗</span></a>`).join('')}</span>`:''}</figcaption></figure>
  <div class="ask">Your call</div>
  <div class="opts n${q.options.length}" role="radiogroup" aria-label="Decision">
    ${q.options.map((o,i)=>{ const sel=a.optionId===o.id||pending[q.id]===i;
      return `<button class="opt ${esc(o.tone)}${sel?' sel':''}" role="radio" aria-checked="${sel}" data-opt="${i}" data-p="${p}">
        ${o.recommended?'<span class="rec">Recommended</span>':''}
        <span class="head"><span class="key">${i+1}</span><span class="name">${esc(o.name)}</span>
          <svg class="mark" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M7 12.5l3.2 3.2L17 9"/></svg></span>
        <span class="sub">${esc(o.sub)}</span>
        ${o.impact?`<span class="impl">${o.impact}</span>`:''}
      </button>`;}).join('')}
  </div>
  <div class="extra">
    ${q.options.map((o,i)=>o.picks?picksHTML(q,o,i,a,p):'').join('')}
    <div class="free"><label for="note-${esc(q.id)}">Your words (optional, saved with your answer)</label><textarea id="note-${esc(q.id)}" data-note data-p="${p}" placeholder="${esc(q.notePrompt||PAGE.notePrompt||'Anything we should know')}">${esc(a.note||'')}</textarea></div>
  </div></div>`;
}
function rows(){ return Q.flatMap((c,k)=>parts(c).map((q,pi)=>[q,k,pi,c])); }
function summaryHTML(){
  const done=answered();
  return `
  <div class="eyebrow"><span class="tick">Summary</span><span>·</span><span id="who">${done} of ${TOTAL} answered</span></div>
  <h1>${done===TOTAL?`All ${TOTAL} answered. Thank you.`:`${done} of ${TOTAL} answered.`}</h1>
  <p class="lead">${done===TOTAL?esc(PAGE.thanks||'Everything is saved on this page.'):'Tap “answer” on a row to jump back to it. Everything picked so far is already saved.'}</p>
  <div class="sum">
    <div><h3>Your answers</h3><table>${rows().map(([q,k,pi,c])=>{ const a=answers[q.id]||{}; const o=optOf(q,a);
      return `<tr><td>${esc(c.tickets.map(t=>t.label||t.id).join(', ')||c.short)}${pi?` (part ${pi+1})`:''}</td><td>${esc(q.question)}${a.picks&&a.picks.length?`<span class="note">${esc(a.picks.join(', '))}</span>`:''}${a.note?`<span class="note">Note: ${esc(a.note)}</span>`:''}</td><td>${o?`<span class="pill ${esc(o.tone)}">${esc(o.name)}</span>`:`<button class="jump" data-go="${k+1}">answer</button>`}</td></tr>`;}).join('')}</table></div>
    <div><h3>Copy answers</h3><textarea class="copybox" id="copybox" readonly>${esc(answersText())}</textarea></div>
  </div>
  <div class="nav">
    <button class="btn ghost" data-go="${TOTAL}">← Back</button>
    <span style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end"><button class="btn" data-go="0">Overview</button><button class="btn primary" id="copy">Copy answers</button></span>
  </div>`;
}
function answersText(){
  const lines=[PAGE.title+'. Answers as of '+new Date().toLocaleString(),''];
  rows().forEach(([q,k,pi,c])=>{const a=answers[q.id]||{}; const o=optOf(q,a);
    lines.push(`${c.tickets.map(t=>t.id).join(', ')||'-'} | ${c.short}${pi?` (part ${pi+1})`:''} | ${o?o.name:'(unanswered)'}${a.picks&&a.picks.length?' | '+a.picks.join(', '):''}${a.note?' | note: '+a.note:''}`);});
  return lines.join('\n');
}
async function fillSummary(el){
  if(!user) return;
  const ids=[...new Set(Object.values(answers).map(a=>a.by).filter(Boolean))];
  if(!ids.length) return;
  try{ const ps=await user.profiles(ids); const names=ids.map(i=>ps[i]&&ps[i].name).filter(Boolean);
    const who=el.querySelector('#who'); if(who&&names.length) who.textContent += ' · by '+names.join(', '); }catch(e){}
}
function runCounters(el){
  const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
  el.querySelectorAll('[data-count]').forEach((n,i)=>{
    const target=+n.dataset.count; if(reduce){n.textContent=target;return;}
    const t0=performance.now()+250+i*220, dur=900;
    const step=now=>{const p=Math.min(1,Math.max(0,(now-t0)/dur)); const e=1-Math.pow(1-p,3); n.textContent=Math.round(target*e); if(p<1) requestAnimationFrame(step);};
    requestAnimationFrame(step);
  });
}

/* ---------- interaction ---------- */
function wire(el){
  el.querySelectorAll('[data-go]').forEach(b=>{ b.addEventListener('click',()=>go(+b.dataset.go));
    if(b.tagName==='LI') b.addEventListener('keydown',e=>{ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); go(+b.dataset.go);} }); });
  el.querySelectorAll('.opt').forEach(b=>b.addEventListener('click',()=>pick(+b.dataset.opt,+b.dataset.p)));
  el.querySelectorAll('[data-note]').forEach(note=>note.addEventListener('input',debounce(()=>saveField('note',note.value.trim(),+note.dataset.p),600)));
  el.querySelectorAll('.part').forEach(pe=>{ const p=+pe.dataset.part;
    pe.querySelectorAll('[data-pick]').forEach(c=>c.addEventListener('change',()=>picksChanged(pe,p,+c.dataset.pick))); });
  const nx=el.querySelector('#next'); if(nx) nx.addEventListener('click',next);
  const ur=el.querySelector('#urgent'); if(ur) ur.addEventListener('click',()=>{ mode='urgent'; go(Q.findIndex(q=>q.urgent&&!isDone(q))+1); });
  const cp=el.querySelector('#copy'); if(cp) cp.addEventListener('click',copyAnswers);
}
function debounce(fn,ms){let t;return()=>{clearTimeout(t);t=setTimeout(fn,ms);};}
function go(n){ if(n<0||n>TOTAL+1) return; const dir=n<idx?-1:1; idx=n; render(dir); }
function next(){
  const q=Q[idx-1];
  if(q && anyDone(q) && !isDone(q)){
    const p=parts(q).findIndex(x=>!done1(x)), t=stage.querySelector(`.screen:not(.leaving) .part[data-part="${p}"]`);
    if(t) t.scrollIntoView({behavior:'smooth',block:'start'}); toast('Part '+(p+1)+' still needs an answer'); return;
  }
  if(mode==='urgent'){ const u=Q.findIndex((x,i)=>x.urgent&&!isDone(x)&&i!==idx-1); if(u>=0){ go(u+1); return; } mode=''; toast('Urgent ones done'); }
  go(idx+1);
}
function base(q,p){ const c=Q[idx-1];
  return {v:1, page:PAGE.slug, qid:q.id, card:c.id, part:p, section:c.section, tickets:c.tickets.map(t=>t.id).join(', '), question:q.question, optionId:'', choice:'', label:'', picks:[], note:'', by:'', at:''}; }
function partQ(p){ const c=Q[idx-1]; return c ? parts(c)[p||0] : null; }
function partEl(p){ const scr=stage.querySelector('.screen:not(.leaving)'); return scr && (scr.querySelector(`.part[data-part="${p}"]`)||scr); }
function refreshNext(){ const q=Q[idx-1], nx=stage.querySelector('.screen:not(.leaving) #next'); if(q&&nx){ nx.textContent=nextLabel(q); nx.classList.toggle('primary',isDone(q)); } }
function markSel(el,i){ el.querySelectorAll('.opt').forEach((b,j)=>{const on=j===i; b.classList.toggle('sel',on); b.setAttribute('aria-checked',on);}); }
function setPickMsg(el,i,q){ const d=el.querySelector(`.extra [data-for="${i}"] .pickmsg`); if(!d) return; const o=q.options[i], n=el.querySelectorAll(`[data-pick="${i}"]:checked`).length, short=pending[q.id]===i&&n<o.picks.min;
  d.classList.toggle('warn',short); d.textContent= short?`Tick at least ${o.picks.min} to save this answer.`:(o.picks.hint||''); }
function pick(i,p){
  p=p||0; const q=partQ(p); if(!q) return; const o=q.options[i]; if(!o) return; const el=partEl(p);
  markSel(el,i);
  el.querySelectorAll('.extra [data-for]').forEach(d=>{ const k=+d.dataset.for; d.hidden = !(k===i || (q.options[k].picks||{}).always); });
  el.querySelectorAll('[data-pick]').forEach(c=>{ if(+c.dataset.pick!==i) c.checked=false; });
  el.querySelectorAll('.units details').forEach(countGroup);
  const prev=answers[q.id]||{};
  const keep = o.picks ? [...el.querySelectorAll(`[data-pick="${i}"]:checked`)].map(c=>c.value) : [];
  if(o.picks && keep.length<o.picks.min){ pending[q.id]=i; setPickMsg(el,i,q); if(prev.optionId) unpick(q,p,true); refreshNext(); return; }
  delete pending[q.id];
  answers[q.id]=Object.assign(base(q,p), {optionId:o.id, choice:o.tone, label:o.name, picks:keep, note:prev.note||'', by:meId||prev.by||'', at:new Date().toISOString()});
  if(o.picks) setPickMsg(el,i,q);
  persistLocal(); updateBar(); refreshNext(); save(q.id);
}
function countGroup(d){ const n=d.querySelectorAll('[data-pick]:checked').length, t=d.querySelectorAll('[data-pick]').length, cnt=d.querySelector('.cnt'); if(cnt){ cnt.textContent=(n?n+' on · ':'')+t; cnt.classList.toggle('on',!!n); } }
function picksChanged(pe,p,i){
  const q=partQ(p); if(!q) return; const o=q.options[i];
  pe.querySelectorAll('.units details').forEach(countGroup);
  const on=[...pe.querySelectorAll(`[data-pick="${i}"]:checked`)].map(c=>c.value), a=answers[q.id]||{};
  const mine = a.optionId===o.id || pending[q.id]===i;
  if(!mine){ if(on.length) pick(i,p); return; }
  if(on.length<o.picks.min){
    if(o.picks.always && !on.length){ delete pending[q.id]; markSel(pe,-1); unpick(q,p,false); setPickMsg(pe,i,q); return; }
    pending[q.id]=i; setPickMsg(pe,i,q); if(a.optionId) unpick(q,p,true); refreshNext(); return;
  }
  if(pending[q.id]===i){ pick(i,p); return; }
  a.picks=on; a.at=new Date().toISOString(); a.by=meId||a.by||''; answers[q.id]=a; persistLocal(); save(q.id); setPickMsg(pe,i,q);
}
async function unpick(q,p,keepSel){
  if(!keepSel){ const el=partEl(p); if(el) markSel(el,-1); }
  const note=(answers[q.id]||{}).note;
  delete answers[q.id]; persistLocal(); updateBar(); refreshNext();
  while(writing[q.id]) await new Promise(r=>setTimeout(r,100));
  queued[q.id]=false;
  if(!db) return;
  try{ if(!answers[q.id]) await db.doc('answers/'+q.id).delete(); setSave('ok','Saved '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})); }catch(e){ console.warn('unpick delete failed', e); }
  if(note) saveField('note',note,p);
}
function saveField(field,val,p){ const q=partQ(p); if(!q) return; const a=answers[q.id]||base(q,p); if(a[field]===val) return; a[field]=val; a.at=new Date().toISOString(); a.by=meId||a.by||''; answers[q.id]=a; persistLocal(); save(q.id); }
const writing={}, queued={};
async function save(qid){
  if(!db){ setSave('local','Saved on this device only'); return; }
  if(writing[qid]){ queued[qid]=true; return; }
  writing[qid]=true; setSave('busy','Saving…');
  try{ const r=Object.assign({},answers[qid]); delete r.synced; await db.doc('answers/'+qid).set(r); setSave('ok','Saved '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})); }
  catch(e){ console.warn('save failed', e); setSave('local', e&&e.code==='invalid_argument' ? 'Saved on this device only: you need Contributor access to save here' : 'Saved on this device only (store unreachable)'); }
  writing[qid]=false; if(queued[qid]){ queued[qid]=false; if(answers[qid]) save(qid); }
}
async function copyAnswers(){
  const txt=answersText(); const box=$('copybox'); if(box) box.value=txt;
  try{ await navigator.clipboard.writeText(txt); toast('Answers copied'); }
  catch(e){ if(box){box.focus();box.select();} toast('Select the text above and copy it'); }
}
document.addEventListener('keydown',e=>{
  if(e.target.matches('input,textarea')) return;
  if(e.key==='ArrowRight'||e.key==='Enter'&&!e.target.matches('button,a,li')){ if(idx>=1&&idx<=TOTAL) next(); else go(idx+1); }
  else if(e.key==='ArrowLeft'){ go(idx-1); }
  else if(e.key==='Escape'){ go(0); }
  else if(/^[1-9]$/.test(e.key) && idx>=1 && idx<=TOTAL){ pick(+e.key-1,0); }
});

/* ---------- storage: artifact db ---------- */
async function boot(){
  document.title = PAGE.title;
  render(1);
  try{
    const [d,u]=await Promise.all([claude.use('db'), claude.use('user')]);
    db=d; user=u;
    if(u){ try{ meId=await u.id(); }catch(e){} }
    if(!db){ setSave('local','Saved on this device only'); return; }
    let first=true; const timer=setTimeout(()=>{ if(first) setSave('local','Store slow to answer; picks are kept on this device'); },10000);
    db.collection('answers').onSnapshot(snap=>{
      clearTimeout(timer); let changed=false;
      snap.docs.forEach(d=>{ const r=d.data(); if(!r||!r.qid) return; const cur=answers[r.qid];
        if(!cur || (r.at||'')>(cur.at||'')){ answers[r.qid]=r; changed=true; } });
      const ids=new Set(snap.docs.map(d=>d.id));
      if(!snap.metadata.fromCache) Object.keys(answers).forEach(k=>{ if(!ids.has(k) && answers[k].synced){ delete answers[k]; changed=true; } });
      snap.docs.forEach(d=>{ const r=answers[d.id]; if(r) r.synced=true; });
      first=false;
      if(changed){ persistLocal(); updateBar(); const el=stage.querySelector('.screen:not(.leaving)');
        const busy=document.activeElement&&document.activeElement.matches('textarea,input');
        if(!busy){ if(idx>TOTAL||idx===0) render(1); else if(el){ const y=window.scrollY; el.innerHTML=questionHTML(Q[idx-1]); el.classList.add('ready'); wire(el); window.scrollTo(0,y);} } }
      if(!snap.metadata.fromCache) setSave('ok', Object.keys(answers).length? 'Saved to this page' : 'Ready to save');
    }, err=>{ console.warn('db listener', err); setSave('local','Saved on this device only'); });
  }catch(e){ console.warn('boot', e); setSave('local','Saved on this device only'); }
}
boot();
})();
