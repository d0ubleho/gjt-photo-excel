'use strict';
const $ = id => document.getElementById(id);
const photos = {photo:[],sticker:[]};
const keys = ['department','application','applicant'];
const forms = [];
const maxForms = 20;
let currentId, busy = false, blobUrl;
const active = () => forms.find(f=>f.id===currentId);
const empty = () => ({name:'',category:'',asset:'',old:'',quantity:'',photo:'',sticker:''});
function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  Object.assign(node,attrs);
  if (text) node.textContent = text;
  return node;
}
function lock(on) {
  busy = on;
  document.querySelectorAll('button,input,select').forEach(n => n.disabled = on);
  if (!on && !forms.length) $('export').disabled = $('exportAll').disabled = true;
}
function summary() {
  const items = forms.flatMap(f=>f.items);
  $('ready').textContent = forms.length ? `전체 신청서 ${forms.length}장 · 품목 ${items.length}개 · 비품 사진 미선택 ${items.filter(r=>!r.photo).length}개 · 스티커 사진 미선택 ${items.filter(r=>!r.sticker).length}개` : '저장할 신청서가 없습니다.';
  if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = undefined; $('result').replaceChildren(); }
}
function autoEquipment() {
  const one = forms.length===1 && forms[0].items.length===1 && photos.photo.length===1;
  for (const f of forms) for (const r of f.items) {
    if (!r.manualPhoto) r.photo = one ? photos.photo[0].id : '';
  }
}
function label(text, node, cls) {
  const l = el('label',text,{className:cls||''}); l.append(node); return l;
}
function input(r,k,opts) {
  const n = el('input','',opts);
  n.value = r[k] ?? '';
  n.addEventListener('input',()=>{
    r[k]=n.value;
    if ((k==='asset' || k==='old') && r.sticker && !r.manualSticker) {
      r.sticker='';
      n.closest('article').dispatchEvent(new Event('sticker-reset'));
    }
    summary();
  });
  return n;
}
function picker(r,k,title) {
  const s = el('select'), pic = el('img','',{className:'thumb',hidden:true});
  s.append(el('option','선택 안 함',{value:''}));
  for (const [i,p] of photos[k].entries()) {
    s.append(el('option',`${i+1}. ${p.name}`,{value:p.id}));
  }
  s.value = r[k] || '';
  function thumb() {
    pic.hidden = !s.value;
    if (s.value) { pic.src = 'image/'+s.value; pic.alt = photos[k].find(p=>p.id===s.value)?.name ?? title; }
    else pic.removeAttribute('src');
  }
  s.addEventListener('change',()=>{
    r[k]=s.value;
    if(k==='sticker') r.manualSticker=true;
    else r.manualPhoto=true;
    status();
    thumb();
    summary();
  });
  thumb();
  const group = el('div'), note = el('small','',{className:'photo-note'});
  function status() {
    note.textContent = k==='photo' && r.photo && !r.manualPhoto ? '자동 연결' :
      (!r[k] && photos[k].length ? '사진 선택 필요' : '');
    note.hidden = !note.textContent;
  }
  status();
  group.append(label(title,s),note,pic);
  if (k==='sticker') {group.resetSticker=()=>{s.value=''; status(); thumb();};}
  return group;
}
function render() {
  autoEquipment();
  const form = active();
  $('editor').hidden = !form;
  $('emptyForms').hidden = Boolean(form);
  $('formCount').textContent = `${forms.length}장`;
  $('current').replaceChildren(...forms.map((f,i)=>el('option',formLabel(f,i),{value:f.id})));
  $('rows').replaceChildren();
  if (!form) { summary(); lock(busy); return; }
  $('current').value = form.id;
  $('source').replaceChildren(el('a','신청서 사진 보기',{href:'image/'+form.id,target:'_blank',rel:'noopener'}));
  keys.forEach(k=>$(k).value=form.header[k]);
  const notes = [...form.notes];
  const number = form.header.application.trim().toUpperCase();
  if (number && forms.some(f=>f!==form && f.header.application.trim().toUpperCase()===number)) {
    notes.push('같은 신청번호의 사진이 있습니다. 중복 사진이면 신청서 제외를 눌러 주세요.');
  }
  $('notes').replaceChildren(...notes.map(n=>el('li',n)));
  $('notes').hidden = !notes.length;
  const items = form.items;
  items.forEach((r,i)=>{
    const box = el('article'), bar = el('div','',{className:'rowbar'}), del = el('button','삭제',{type:'button'});
    del.addEventListener('click',()=>{items.splice(i,1); render();});
    bar.append(el('strong',`품목 ${i+1}`),del);
    const fields = el('div','',{className:'fields'}), category = el('select');
    for (const opt of ['', '불용','반납']) category.append(el('option',opt||'선택',{value:opt}));
    category.value = r.category;
    category.addEventListener('change',()=>{r.category=category.value; summary();});
    fields.append(label('품명',input(r,'name',{maxLength:80}),'wide'),label('구분',category),
      label('수량',input(r,'quantity',{type:'number',min:'1',max:'9999',inputMode:'numeric'})),
      label('자산번호',input(r,'asset',{maxLength:10,inputMode:'numeric'})),
      label('예전 비품번호 (있을 때만)',input(r,'old',{maxLength:15,inputMode:'numeric'})));
    const pictures = el('div','',{className:'pictures'});
    const stickerPicker=picker(r,'sticker','스티커 사진');
    box.addEventListener('sticker-reset',stickerPicker.resetSticker);
    pictures.append(picker(r,'photo','비품 사진'),stickerPicker);
    box.append(bar,fields,pictures);
    $('rows').append(box);
  });
  summary();
  lock(busy);
}
function formLabel(f,i) {
  return `${i+1}번 · ${f.header.application.trim() || f.name} · 품목 ${f.items.length}개`;
}
async function json(url, init) {
  const res = await fetch(url, init);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || '요청에 실패했습니다.');
  return data;
}
function post(body) {
  return {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
}
async function match(force=false) {
  const items = forms.flatMap(f=>f.items);
  if (!items.length || !photos.sticker.length) return;
  const data = await json('match',post({items:items.map(({asset,old})=>({asset,old})),stickers:photos.sticker.map(p=>p.id)}));
  const currentRows = force ? new Set(active()?.items) : null;
  data.matches.forEach((m,i)=>{
    const r = items[i];
    if (currentRows?.has(r) || !r.manualSticker) { r.sticker = m[0] || ''; r.manualSticker=false; }
  });
}
for (const k of ['form','sticker','photo']) {
  $(k).addEventListener('change',async ()=>{
    let files = Array.from($(k).files);
    $(k).value='';
    if (!files.length || busy) return;
    lock(true);
    const errors=[];
    try {
      if (k==='form' && files.length + forms.length > maxForms) {
        files=files.slice(0,maxForms-forms.length);
        errors.push(`한 번에 신청서 ${maxForms}장까지 올릴 수 있습니다. 초과분은 다음 작업에서 올려 주세요.`);
      }
      for (const [i,file] of files.entries()) {
        $('status').textContent = `사진 처리 중 (${i+1}/${files.length})`;
        try {
          const p = await json('scan?kind='+k,{method:'POST',body:file,headers:{'X-Photo-Name':encodeURIComponent(file.name)}});
          if (k==='form') {
            forms.push({...p,items:p.items.map(r=>({...empty(),...r}))});
            currentId ??= p.id;
          } else {
            photos[k].push(p);
            $(k+'Count').textContent = `${photos[k].length}장`;
          }
        } catch(err) {errors.push(file.name + ': ' + err.message);}
      }
      if (k!=='photo') await match();
      $('status').textContent = errors.length ? errors.join(' / ') : '사진 처리가 끝났습니다.';
    } catch(e) {
      $('status').textContent = e.message;
    } finally {lock(false); render();}
  });
}
$('current').addEventListener('change',()=>{currentId=$('current').value;render();});
$('removeForm').addEventListener('click',()=>{
  const i = forms.findIndex(f=>f.id===currentId);
  if (i<0 || !confirm(`신청서 ${i+1}번을 이번 저장에서 제외할까요?`)) return;
  forms.splice(i,1);
  currentId=forms[Math.min(i,forms.length-1)]?.id;
  render();
});
$('add').addEventListener('click',()=>{
  if (active()?.items.length>=50) {
    $('status').textContent='엑셀 파일 하나에 품목을 최대 50개까지 저장할 수 있습니다.';
    return;
  }
  active()?.items.push(empty());
  render();
});
$('match').addEventListener('click',async ()=>{
  lock(true);
  try {await match(true); $('status').textContent='자산번호를 기준으로 스티커 사진을 다시 찾았습니다.';}
  catch(e){$('status').textContent=e.message;}
  finally{lock(false);render();}
});
keys.forEach(k=>$(k).addEventListener('input',()=>{
  const form = active();
  if (!form) return;
  form.header[k]=$(k).value;
  const i=forms.indexOf(form);
  $('current').options[i].textContent=formLabel(form,i);
  summary();
}));
async function download(all) {
  if (!active()) return;
  lock(true);
  if(blobUrl) {URL.revokeObjectURL(blobUrl); blobUrl=undefined;}
  const toPayload = ({header,items}) => ({header,items});
  const current = toPayload(active());
  $('result').textContent=all ? `신청서 ${forms.length}장의 엑셀을 만드는 중입니다.` : '엑셀을 만드는 중입니다.';
  try {
    const response=await fetch(all?'export-batch':'export',post(all?{forms:forms.map(toPayload)}:current));
    if(!response.ok) throw new Error((await response.json()).error);
    blobUrl=URL.createObjectURL(await response.blob());
    const a=el('a',all?'ZIP 파일 받기':'엑셀 파일 받기',{href:blobUrl,
      download:all?'회수 완료 사진 모음.zip':current.header.application.trim()+' 회수 완료 사진.xlsx',className:'download'});
    $('result').replaceChildren(a); a.click();
  } catch(e) {$('result').textContent=e.message;}
  finally {lock(false);}
}
$('export').addEventListener('click',()=>download(false));
$('exportAll').addEventListener('click',()=>download(true));
render();
