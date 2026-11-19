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
/* What user.can('data.write') said: true, false, or null (not told / no user capability). */
let canWrite = null;
/* Why answers are not reaching the author (any entry = fail loud). */
const broken = new Set();
const AUTHOR = PAGE.author || PAGE.discussWith || 'the person who sent you this page';
const LS = 'qw-' + PAGE.slug + '-answers-v1', LSPOS = 'qw-' + PAGE.slug + '-pos-v1';
try{ const raw=localStorage.getItem(LS); if(raw) Object.assign(answers, JSON.parse(raw)); const p=parseInt(localStorage.getItem(LSPOS)||'0',10); if(p>=0&&p<=TOTAL+1) idx=p; }catch(e){}
function persistLocal(){ try{ localStorage.setItem(LS, JSON.stringify(answers)); localStorage.setItem(LSPOS,String(idx)); }catch(e){} }

const $ = id => document.getElementById(id);
const nosave=$('nosave'), nosaveTxt=$('nosavetxt'), stage=$('stage'), bar=$('bar'), fill=$('fill'), chips=$('chips'), saveEl=$('save'), saveTxt=$('savetxt'), toastEl=$('toast');
let toastT; function toast(msg){ toastEl.textContent=msg; toastEl.classList.add('show'); clearTimeout(toastT); toastT=setTimeout(()=>toastEl.classList.remove('show'),2200); }
function setSave(state,text){ saveEl.className='save '+state; saveTxt.textContent=text; }
const WHY = {nodb:'this page could not open its answer store', listener:'this page could not reach its answer store', slow:'the answer store is not answering', write:'the last save was refused', perm:'your access to this page only lets you view it', refused:'the page refused the save; if you were shared as Viewer or Commenter, ask '+AUTHOR+' to make you a Contributor'};
/* A refused set() arrives as invalid_argument both for a viewer below Contributor and for a malformed write.
   Only claim view-only when the platform said so; if it said this viewer CAN write, it is a plain refused save. */
function saveFailReason(e, can){ return !(e&&e.code==='invalid_argument') || can===true ? 'write' : 'refused'; }
function fail(why,quiet){ broken.add(why); paintBroken(!quiet); }
function heal(...whys){ whys.forEach(w=>broken.delete(w)); paintBroken(false); }
function paintBroken(loud){
  const on=broken.size>0; nosave.hidden=!on;
  if(!on) return;
  const why=[...broken].map(w=>WHY[w]||w).join('; ');
  nosaveTxt.innerHTML=`<b>Your answers are NOT reaching ${esc(AUTHOR)}.</b> They are only kept in this browser (${esc(why)}). Tap “Copy all my answers” and paste the text to ${esc(AUTHOR)} in Slack or email.`;
  setSave('local','NOT sent to '+AUTHOR);
  if(loud) toast('Not sent to '+AUTHOR+'. Copy all your answers.');
}
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
      s+=`<text class="cu" x="${pad+w+6}" y="${y+15}" style="font-size:13px">${esc(it.text!=null?it.text:it.value)}</text>`; });
    return s+'</svg>';
  },
  split(v){
    const tot=v.parts.reduce((a,p)=>a+p.value,0)||1;
    return `<div class="qv-split"><div class="qv-split-bar" role="img" aria-label="${esc(v.parts.map(p=>p.label+' '+p.value).join('; '))}">${v.parts.map(p=>`<i style="--w:${(p.value/tot*100).toFixed(1)}%;background:${TONE[p.tone]||TONE.accent}"></i>`).join('')}</div><div class="qv-legend">${v.parts.map(p=>`<span><i style="background:${TONE[p.tone]||TONE.accent}"></i><b class="num cu">${esc(p.text!=null?p.text:p.value)}</b> ${esc(p.label)}</span>`).join('')}</div></div>`;
  },
  flow(v){
    return `<ol class="qv-flow">${v.steps.map((s,i)=>`<li class="t-${esc(s.tone||'accent')}" style="--i:${i}"><b>${esc(s.label)}</b>${s.note?`<span>${esc(s.note)}</span>`:''}</li>`).join('')}</ol>`;
  },
  tree(v){
    let k=0;
    const node = n => typeof n === 'string' || !n.ask
      ? `<div class="qv-leaf t-${esc(n.tone||'accent')}">${esc(n.label||n)}</div>`
      : `<div class="qv-ask">${esc(n.ask)}</div><ul>${(n.branches||[]).map(b=>`<li style="--i:${++k}"><span class="qv-br">${esc(b.when)}</span>${node(b.then)}</li>`).join('')}</ul>`;
    return `<div class="qv-tree">${node(v.root)}</div>`;
  },
  beforeAfter(v){
    const col = (c, cls) => `<div class="qv-col ${cls}"><div class="qv-h">${esc(c.label)}</div><ul>${c.lines.map((l,i)=>`<li class="t-${esc(l.tone||'')}" style="--i:${i}">${esc(l.text||l)}</li>`).join('')}</ul></div>`;
    return `<div class="qv-ba">${col(v.before,'before')}<div class="qv-arrow" aria-hidden="true">→</div>${col(v.after,'after')}</div>`;
  },
  steps(v){
    return `<ol class="qv-steps">${v.items.map((s,i)=>`<li class="t-${esc(s.tone||'accent')}" style="--i:${i}"><span class="num">${esc(s.when||'')}</span><b>${esc(s.label)}</b>${s.note?`<span>${esc(s.note)}</span>`:''}</li>`).join('')}</ol>`;
  },
  table(v){
    return `<div class="qv-table"><table><thead><tr>${v.cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${v.rows.map((r,i)=>`<tr style="--i:${i}"${(v.highlight||[]).includes(i)?' class="hl-row"':''}>${r.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
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
  if(old){ old.classList.add('leaving'); if(dir<0) old.classList.add('back'); setTimeout(()=>old.remove(),320); }
  const el=document.createElement('section'); el.className='screen'+(dir<0?' back':'');
  el.innerHTML = idx===0 ? openingHTML() : idx>TOTAL ? summaryHTML() : questionHTML(Q[idx-1]);
  stage.appendChild(el);
  requestAnimationFrame(()=>requestAnimationFrame(()=>el.classList.add('ready')));
  wire(el); bar.hidden = idx===0; updateBar(); persistLocal();
  countUp(el);
  if(idx>TOTAL) fillSummary(el);
  window.scrollTo({top:0,behavior:'smooth'});
  const h=el.querySelector('h1,h2'); if(h){h.setAttribute('tabindex','-1'); h.focus({preventScroll:true});}
}
function updateBar(){
  const pct = idx===0?0: idx>TOTAL?100 : Math.round(answered()/TOTAL*100);
  fill.style.transform='scaleX('+(pct/100)+')';
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
  const stats=(PAGE.stats||[]).map(s=>`<div class="stat"><span class="big num cu">${+s.value}</span><span class="what">${esc(s.what)}</span><span class="how">${esc(s.how||'')}</span></div>`).join('');
  const total=lr&&lr.decided?lr.decided+TOTAL:0;
  return `
  <div class="eyebrow"><span class="tick">${esc(PAGE.eyebrow||PAGE.title)}</span>${lr&&lr.url?`<span>·</span>${ext(lr.url, esc(lr.label||'last round'))}`:''}</div>
  <h1>${head}</h1>
  ${PAGE.lead?`<p class="lead">${esc(PAGE.lead)}</p>`:''}
  ${compact?'':`<div class="stats">${stats}
    <div class="stat you"><span class="big num cu">${left}</span><span class="what">need your answer</span><span class="how">${done?`<b>${done} done</b>`:''}${done&&urgent?' · ':''}${urgent?plural(urgent,'urgent one'):''}</span></div>
  </div>`}
  ${total?`<div class="split" aria-hidden="true"><i class="done" style="--w:${(lr.decided/total*100).toFixed(1)}%"></i><i class="you" style="--w:${(TOTAL/total*100).toFixed(1)}%"></i></div>
  <div class="legend"><span><b>${lr.decided}</b> ${esc(lr.decidedLabel||'decided')}</span><span><b>${TOTAL}</b> for you</span></div>`:''}
  ${compact?'':`<ol class="cards7">
    ${Q.map((q,i)=>{const d=isDone(q); return `<li class="${d?'done':''}" style="animation-delay:${Math.min(.6+i*.08,2)}s" data-go="${i+1}" tabindex="0" role="link"><span class="n">${d?'✓':i+1}</span><span>${SECTIONS.length>1?`<b>${esc(secName(q.section))}:</b> `:''}${esc(q.short)}${q.parts&&q.parts.length?` <span class="num" style="font-size:12px;color:var(--muted)">(${q.parts.length+1} parts)</span>`:''}${q.badge?` <span class="badge">${esc(q.badge)}</span>`:''}</span></li>`;}).join('')}
  </ol>`}
  <p class="whyline">${esc(PAGE.whyline||'The recommended answer is marked on each screen. “Let’s discuss” parks a question for a call. The text box under each question is always there for your own words.')}</p>
  <div class="nav"><span class="hint" style="margin:0"><kbd>1</kbd>–<kbd>4</kbd> pick · <kbd>→</kbd> next · <kbd>←</kbd> back</span>
    <span style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end">${urgent&&TOTAL>8?`<button class="btn" id="urgent">Urgent first (${urgent}) →</button>`:''}<button class="btn primary" data-go="${done&&left?Q.findIndex(q=>!isDone(q))+1:1}">${done?'Continue':'Start'} →</button></span></div>
  ${done?COPYROW:''}`;
}
const COPYROW = '<p class="copyrow"><button type="button" class="linkbtn" data-copyall>Copy all my answers</button></p>';
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
  <p class="hint"><kbd>1</kbd>–<kbd>${Math.min(9,q.options.length)}</kbd> pick${ps.length>1?' (keys set part 1)':''} · <kbd>→</kbd> next · <kbd>←</kbd> back · <kbd>Esc</kbd> overview</p>
  ${COPYROW}`;
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
  ${q.visual||q.example||facts.length||(q.links&&q.links.length)?`<figure class="figure">${visual(q.visual)}<figcaption>${q.example?`<span class="lbl">Worked example</span>${esc(q.example)}`:''}${facts.map(f=>`<span class="ex ph">${esc(f.text)}</span>`).join('')}${q.links&&q.links.length?`<span class="links">${q.links.map(l=>`<a class="hub" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} <span aria-hidden="true">↗</span></a>`).join('')}</span>`:''}</figcaption></figure>`:''}
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
  <h1>${done===TOTAL?`<span class="donecheck" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M7 12.5l3.2 3.2L17 9"/></svg></span>All ${TOTAL} answered. Thank you.`:`${done} of ${TOTAL} answered.`}</h1>
  <p class="lead">${broken.size?`Your answers are NOT reaching ${esc(AUTHOR)} yet. Copy them below and send them in Slack or email.`:done===TOTAL?esc(PAGE.thanks||'Everything is saved on this page.'):'Tap “answer” on a row to jump back to it. Everything picked so far is already saved.'}</p>
  <div class="sum${done===TOTAL?' all':''}">
    <div><h3>Your answers</h3><table>${rows().map(([q,k,pi,c],ri)=>{ const a=answers[q.id]||{}; const o=optOf(q,a);
      return `<tr style="--i:${Math.min(ri,14)}"><td>${esc(c.tickets.map(t=>t.label||t.id).join(', ')||c.short)}${pi?` (part ${pi+1})`:''}</td><td>${esc(q.question)}${a.picks&&a.picks.length?`<span class="note">${esc(a.picks.join(', '))}</span>`:''}${a.note?`<span class="note">Note: ${esc(a.note)}</span>`:''}</td><td>${o?`<span class="pill ${esc(o.tone)}">${esc(o.name)}</span>`:`<button class="jump" data-go="${k+1}">answer</button>`}</td></tr>`;}).join('')}</table></div>
    <div><h3>All my answers, as text</h3><textarea class="copybox" id="copybox" readonly>${esc(answersText())}</textarea></div>
  </div>
  <div class="nav">
    <button class="btn ghost" data-go="${TOTAL}">← Back</button>
    <span style="display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end"><button class="btn" data-go="0">Overview</button><button class="btn primary" data-copyall>Copy all my answers</button></span>
  </div>`;
}
/* Plain text, one line per question (and part), ready to paste in Slack or email. */
function answersText(){
  const flat=s=>String(s||'').replace(/\s+/g,' ').trim();
  const lines=[`${PAGE.title}: my answers (${answered()} of ${TOTAL} answered, ${new Date().toLocaleString()})`];
  rows().forEach(([q,k,pi,c])=>{const a=answers[q.id]||{}; const o=optOf(q,a); const t=c.tickets.map(x=>x.id).join(', ');
    lines.push(`${k+1}${pi?String.fromCharCode(97+pi):''}. ${flat(c.short)}${pi?` (part ${pi+1})`:''}${t?` [${t}]`:''}: ${o?flat(o.name):'not answered'}${a.picks&&a.picks.length?'. Ticked: '+a.picks.map(flat).join(', '):''}${a.note?'. Note: '+flat(a.note):''}`);});
  lines.push(`Page: ${PAGE.slug}`);
  return lines.join('\n');
}
async function fillSummary(el){
  if(!user) return;
  const ids=[...new Set(Object.values(answers).map(a=>a.by).filter(Boolean))];
  if(!ids.length) return;
  try{ const ps=await user.profiles(ids); const names=ids.map(i=>ps[i]&&ps[i].name).filter(Boolean);
    const who=el.querySelector('#who'); if(who&&names.length) who.textContent += ' · by '+names.join(', '); }catch(e){}
}
/* Numbers count up from 0 to the number already in the text ("$1,250", "38%", "12 of 40"): the
   text is right without JS and under reduced motion; only the first number in it moves. */
function countUp(el){
  if(reduced()) return;
  [...el.querySelectorAll('.cu')].slice(0,16).forEach((n,i)=>{
    const txt=n.textContent, m=/-?\d[\d,]*(\.\d+)?/.exec(txt); if(!m) return;
    const target=parseFloat(m[0].replace(/,/g,'')), dec=(m[1]||'').length-(m[1]?1:0), commas=m[0].includes(',');
    if(!isFinite(target)||target===0) return;
    const fmt=v=>{ const s=v.toFixed(dec); return commas?Number(s).toLocaleString('en-US',{minimumFractionDigits:dec,maximumFractionDigits:dec}):s; };
    const show=v=>{ n.textContent=txt.slice(0,m.index)+fmt(v)+txt.slice(m.index+m[0].length); };
    const t0=performance.now()+200+i*120, dur=800; show(0);
    const step=now=>{ if(!n.isConnected){ return; } const p=Math.min(1,Math.max(0,(now-t0)/dur)); show(p<1?target*(1-Math.pow(1-p,3)):target); if(p<1) requestAnimationFrame(step); else n.textContent=txt; };
    requestAnimationFrame(step);
  });
}

/* ---------- motion: celebrations and milestones (all off under reduced motion) ---------- */
function reduced(){ try{ const d=document.documentElement; return (d&&d.dataset&&d.dataset.motion==='reduce') || matchMedia('(prefers-reduced-motion: reduce)').matches; }catch(e){ return true; } }
/* Pure. Only a reader's own pick reaches this: answers restored from storage or the db never do. */
function celebrateKind(wasDone, nowDone, doneCount, total){ return wasDone||!nowDone ? null : doneCount>=total ? 'final' : 'card'; }
/* Pure. 'half' when a pick takes the count across half (4+ cards), 'done' at the last one. */
function milestoneAt(before, after, total){
  if(!(after>before) || total<1) return null;
  if(after>=total) return before<total ? 'done' : null;
  const half=Math.ceil(total/2);
  return total>=4 && before<half && after>=half ? 'half' : null;
}
function milestoneText(kind, n, total){ return kind==='done' ? `${n} of ${total}, all done` : `${n} of ${total}, ${n*2===total?'halfway there':'past halfway'}`; }
const celebrations=[], seenMs=new Set();
let msT;
function afterPick(wasDone, before, card, from){
  const after=answered(), kind=celebrateKind(wasDone, isDone(card), after, TOTAL), ms=milestoneAt(before, after, TOTAL);
  if(kind){ celebrations.push(kind);
    if(!reduced()){ const W=window.innerWidth||800, H=window.innerHeight||600, shells=kind==='final'?shellPlan(SHELLS, W, H, Math.random):[];
      confetti(kind==='final'?220:70, kind==='final'?null:from, shells); playSound(kind, shells); } }
  if(ms && !seenMs.has(ms)){ seenMs.add(ms); const b=$('milestone'); if(b){ b.textContent=milestoneText(ms, after, TOTAL); b.className='milestone show '+ms; clearTimeout(msT); msT=setTimeout(()=>{ b.className='milestone'; }, ms==='done'?3200:2400); } }
  const tr=fill.parentNode; if(kind && tr && !reduced()){ tr.classList.remove('bump'); void tr.offsetWidth; tr.classList.add('bump'); }
}
/* Pure. The last card's fireworks: n shells, launched one after another across the middle of the screen.
   at = launch delay (ms), rise = flight time (ms); each bursts at (x, y) after at+rise. Sound uses the same plan. */
const SHELLS=6;
function shellPlan(n, W, H, rnd){
  const out=[]; for(let i=0;i<n;i++){ const lane=(i+0.5)/n;
    out.push({at:i*260+Math.round(rnd()*80), rise:620+Math.round(rnd()*260), x:Math.round(W*(0.12+0.76*((lane+rnd()*0.16)%1))), y:Math.round(H*(0.14+0.26*rnd())), c:i}); }
  return out;
}
/* Canvas confetti and fireworks: one fixed canvas, pointer-events none, stops itself
   (about 1.5 s for a card; about 3.5 s for the last one: a two-sided confetti burst plus the shells). */
let cv=null, bits=[], raf=0;
function confetti(n, from, shells){
  if(!document.body || typeof window.innerWidth!=='number') return;
  if(!cv){ cv=document.createElement('canvas'); cv.className='confetti'; cv.setAttribute('aria-hidden','true'); document.body.appendChild(cv); }
  const g=cv.getContext&&cv.getContext('2d'); if(!g) return;
  const W=window.innerWidth, H=window.innerHeight, dpr=Math.min(2,window.devicePixelRatio||1);
  if(cv.width!==Math.round(W*dpr)||cv.height!==Math.round(H*dpr)){ cv.width=Math.round(W*dpr); cv.height=Math.round(H*dpr); }
  g.setTransform(dpr,0,0,dpr,0,0);
  const cs=getComputedStyle(document.documentElement), cols=['--yes','--accent','--discuss','--no'].map(v=>cs.getPropertyValue(v).trim()||'#1D5C8A');
  const r=from&&from.getBoundingClientRect?from.getBoundingClientRect():null, now=performance.now(), L=Math.max(W*0.08,W/2-440), R=Math.min(W*0.92,W/2+440);
  for(let i=0;i<n;i++){
    const big=!r, a=big?Math.PI*(1.15+0.7*Math.random()):Math.PI*(1.05+0.9*Math.random()), sp=big?10+Math.random()*10:6+Math.random()*7;
    const x=big?(i%2?L:R):r.right-24, y=big?H*0.95:r.top+20;
    bits.push({x, y, vx:Math.cos(a)*sp*(big&&i%2?-1:1), vy:Math.sin(a)*sp, w:8+Math.random()*8, h:5+Math.random()*5, rot:Math.random()*6, vr:(Math.random()-.5)*.4, c:cols[i%cols.length], t0:now, life:big?2200:1500});
  }
  (shells||[]).forEach(s=>bits.push({rocket:true, x:s.x, y0:H+8, y:H+8, ty:s.y, c:cols[s.c%cols.length], t0:now+s.at, life:s.rise}));
  if(!raf){ let last=now; const tick=t=>{ const dt=Math.min(2.5,(t-last)/16.7); last=t; g.clearRect(0,0,W,H);
      const keep=[]; bits.forEach(b=>{ const age=t-b.t0; if(age<0){ keep.push(b); return; }
        if(age>=b.life){ if(b.rocket) burst(b, t, keep); return; } keep.push(b);
        if(b.rocket){ const k=age/b.life, e=1-Math.pow(1-k,2.2); b.y=b.y0+(b.ty-b.y0)*e;
          g.globalAlpha=1; g.strokeStyle=b.c; g.lineWidth=2.5; g.beginPath(); g.moveTo(b.x,b.y); g.lineTo(b.x,Math.min(b.y0,b.y+34)); g.stroke();
          g.fillStyle=b.c; g.beginPath(); g.arc(b.x,b.y,3.5,0,7); g.fill(); return; }
        if(b.spark){ b.vy+=0.07*dt; b.vx*=Math.pow(0.965,dt); b.vy*=Math.pow(0.965,dt); b.x+=b.vx*dt; b.y+=b.vy*dt;
          g.globalAlpha=Math.max(0,1-Math.pow(age/b.life,2)); g.fillStyle=b.c; g.beginPath(); g.arc(b.x,b.y,b.s,0,7); g.fill(); return; }
        b.vy+=0.32*dt; b.vx*=Math.pow(0.985,dt); b.x+=b.vx*dt; b.y+=b.vy*dt; b.rot+=b.vr*dt;
        g.globalAlpha=Math.max(0,1-Math.pow(age/b.life,3)); g.save(); g.translate(b.x,b.y); g.rotate(b.rot); g.fillStyle=b.c; g.fillRect(-b.w/2,-b.h/2,b.w,b.h); g.restore(); });
      bits=keep; g.globalAlpha=1;
      if(bits.length) raf=requestAnimationFrame(tick); else { raf=0; g.clearRect(0,0,W,H); } };
    raf=requestAnimationFrame(tick); }
}
/* A rocket reached its height: a ring of 80 sparks in its colour, with a few white glints. */
function burst(b, t, into){
  const n=80, pow=5.5+Math.random()*2.5;
  for(let i=0;i<n;i++){ const a=(i/n)*Math.PI*2+Math.random()*0.08, sp=pow*(0.55+0.45*Math.random());
    into.push({spark:true, x:b.x, y:b.ty, vx:Math.cos(a)*sp, vy:Math.sin(a)*sp, s:i%9===0?2.6:2, c:i%9===0?'#fff':b.c, t0:t, life:1300+Math.random()*500}); }
}

/* ---------- sound: a pop for each answered card, a whistle and a bang per shell on the last one ----------
   Made in the browser (WebAudio, no files). Only after the reader's own tap, never under reduced motion, and a
   mute button in the top bar that this browser remembers. */
const SND='qw-sound-v1', sounds=[];
let muted=false; try{ muted=localStorage.getItem(SND)==='off'; }catch(e){}
let ac=null;
function audio(){ if(ac) return ac; const A=globalThis.AudioContext||globalThis.webkitAudioContext; if(!A) return null; try{ ac=new A(); }catch(e){ ac=null; } return ac; }
function noise(c, dur){ const len=Math.max(1,Math.floor(c.sampleRate*dur)), b=c.createBuffer(1,len,c.sampleRate), d=b.getChannelData(0);
  for(let i=0;i<len;i++) d[i]=(Math.random()*2-1)*Math.pow(1-i/len,2); const s=c.createBufferSource(); s.buffer=b; return s; }
function sPop(c, t, vol){
  const o=c.createOscillator(), g=c.createGain(); o.type='triangle'; o.frequency.setValueAtTime(950,t); o.frequency.exponentialRampToValueAtTime(170,t+0.13);
  g.gain.setValueAtTime(0.0001,t); g.gain.exponentialRampToValueAtTime(vol,t+0.006); g.gain.exponentialRampToValueAtTime(0.0001,t+0.17);
  o.connect(g); g.connect(c.destination); o.start(t); o.stop(t+0.2);
  const n=noise(c,0.07), f=c.createBiquadFilter(), ng=c.createGain(); f.type='bandpass'; f.frequency.value=2600; ng.gain.value=vol*0.7;
  n.connect(f); f.connect(ng); ng.connect(c.destination); n.start(t);
}
function sWhistle(c, t, dur){
  const o=c.createOscillator(), g=c.createGain(); o.type='sine'; o.frequency.setValueAtTime(650,t); o.frequency.exponentialRampToValueAtTime(2300,t+dur);
  g.gain.setValueAtTime(0.0001,t); g.gain.exponentialRampToValueAtTime(0.045,t+0.06); g.gain.setValueAtTime(0.045,t+Math.max(0.07,dur-0.06)); g.gain.exponentialRampToValueAtTime(0.0001,t+dur);
  o.connect(g); g.connect(c.destination); o.start(t); o.stop(t+dur+0.02);
}
function sBang(c, t, vol){
  const n=noise(c,1.1), f=c.createBiquadFilter(), g=c.createGain(); f.type='lowpass'; f.frequency.setValueAtTime(3200,t); f.frequency.exponentialRampToValueAtTime(260,t+0.9);
  g.gain.setValueAtTime(vol,t); g.gain.exponentialRampToValueAtTime(0.0001,t+1.05); n.connect(f); f.connect(g); g.connect(c.destination); n.start(t);
}
function playSound(kind, shells){
  if(muted || reduced()) return; sounds.push(kind); const c=audio(); if(!c) return;
  try{ if(c.state==='suspended') c.resume(); const t=c.currentTime+0.02;
    if(kind!=='final') sPop(c, t, 0.22);
    else { sPop(c, t, 0.22); (shells||[]).forEach(s=>{ sWhistle(c, t+s.at/1000, s.rise/1000); sBang(c, t+(s.at+s.rise)/1000, 0.4); }); }
  }catch(e){ console.warn('sound', e); }
}
function paintSound(){ const b=$('snd'); if(!b) return; b.classList.toggle('muted', muted); b.setAttribute('aria-pressed', String(!muted));
  b.setAttribute('aria-label', muted?'Sound off. Turn sound on':'Sound on. Mute'); b.title=muted?'Sound off':'Sound on'; }
function toggleSound(){ muted=!muted; try{ localStorage.setItem(SND, muted?'off':'on'); }catch(e){} paintSound(); toast(muted?'Sound off':'Sound on'); if(!muted) playSound('preview'); }
{ const b=$('snd'); if(b){ paintSound(); b.addEventListener('click', toggleSound); } }

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
  const card=Q[idx-1], wasDone=isDone(card), before=answered();
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
  const btn=el.querySelectorAll('.opt')[i];
  if(btn && !reduced()){ btn.classList.remove('just'); void btn.offsetWidth; btn.classList.add('just'); setTimeout(()=>btn.classList.remove('just'),600); }
  afterPick(wasDone, before, card, btn);
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
  if(!db){ fail(broken.size?[...broken][0]:'nodb'); return; }
  if(writing[qid]){ queued[qid]=true; return; }
  writing[qid]=true; setSave('busy','Saving…');
  try{ const r=Object.assign({},answers[qid]); delete r.synced; await db.doc('answers/'+qid).set(r); heal('write','slow'); if(!broken.size) setSave('ok','Saved '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})); }
  catch(e){ console.warn('save failed', e); fail(canWrite===false ? 'perm' : saveFailReason(e, canWrite)); }
  writing[qid]=false; if(queued[qid]){ queued[qid]=false; if(answers[qid]) save(qid); }
}
async function copyAnswers(){
  const txt=answersText(); const box=$('copybox'); if(box) box.value=txt;
  try{ await navigator.clipboard.writeText(txt); toast('Copied. Paste it to '+AUTHOR+'.'); }
  catch(e){ if(box){box.focus();box.select();toast('Select the text and copy it');} else { idx=TOTAL+1; render(1); const b2=$('copybox'); if(b2){ b2.focus(); b2.select(); } toast('Select the text in the box and copy it'); } }
}
document.addEventListener('click',e=>{ const b=e.target&&e.target.closest&&e.target.closest('[data-copyall]'); if(b){ e.preventDefault(); copyAnswers(); } });
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
  try{ if(/reduce-motion/.test(location.hash)) document.documentElement.dataset.motion='reduce'; }catch(e){}
  render(1);
  try{
    const [d,u]=await Promise.all([claude.use('db'), claude.use('user')]);
    db=d; user=u;
    if(u){ try{ meId=await u.id(); }catch(e){} try{ const c=await u.can('data.write'); canWrite=(c===true||c===false)?c:null; if(canWrite===false) fail('perm',1); }catch(e){} }
    if(!db){ fail('nodb',1); return; }
    let first=true; const timer=setTimeout(()=>{ if(first) fail('slow',1); },10000);
    db.collection('answers').onSnapshot(snap=>{
      clearTimeout(timer); if(first) heal('slow','listener'); let changed=false;
      snap.docs.forEach(d=>{ const r=d.data(); if(!r||!r.qid) return; const cur=answers[r.qid];
        if(!cur || (r.at||'')>(cur.at||'')){ answers[r.qid]=r; changed=true; } });
      const ids=new Set(snap.docs.map(d=>d.id));
      if(!snap.metadata.fromCache) Object.keys(answers).forEach(k=>{ if(!ids.has(k) && answers[k].synced){ delete answers[k]; changed=true; } });
      snap.docs.forEach(d=>{ const r=answers[d.id]; if(r) r.synced=true; });
      first=false;
      if(changed){ persistLocal(); updateBar(); const el=stage.querySelector('.screen:not(.leaving)');
        const busy=document.activeElement&&document.activeElement.matches('textarea,input');
        if(!busy){ if(idx>TOTAL||idx===0) render(1); else if(el){ const y=window.scrollY; el.innerHTML=questionHTML(Q[idx-1]); el.classList.add('ready'); wire(el); window.scrollTo(0,y);} } }
      if(!snap.metadata.fromCache && !broken.size) setSave('ok', Object.keys(answers).length? 'Saved to this page' : 'Ready to save');
    }, err=>{ clearTimeout(timer); console.warn('db listener', err); fail('listener',1); });
  }catch(e){ console.warn('boot', e); fail('nodb',1); }
}
if(globalThis.__QW_TEST__) globalThis.__QW_TEST__.api={answersText, celebrateKind, shellPlan, saveFailReason, sounds, toggleSound, muted:()=>muted, milestoneAt, milestoneText, celebrations, milestone:()=>{ const b=$('milestone'); return b?b.textContent:''; }, broken, pick:(i,p)=>pick(i,p), go:n=>go(n), state:()=>({idx, answers})};
boot();
})();
