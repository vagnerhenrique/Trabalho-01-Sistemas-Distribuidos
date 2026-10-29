'use strict';
const $ = id => document.getElementById(id);
const state = { sources: [], latestHistory: [], gateway: false, toastTimer: null, lastControlSource: null };
const metricLabels = {temperature:'Temperatura (°C)',humidity:'Umidade (%)',co2:'CO₂ (ppm)',noise:'Ruído (dB)'};
const units = {temperature:'°C',humidity:'%',co2:'ppm',noise:'dB'};
const opLabels = {avg:'Média',min:'Mínimo',max:'Máximo',stddev:'Desvio padrão'};
function val(id){return $(id).value;}
function format(n,dec=1){return Number(n).toLocaleString('pt-BR',{maximumFractionDigits:dec,minimumFractionDigits:dec});}
function el(tag, cls, text){const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;}
function toast(message,error=false){const t=$('toast');t.textContent=message;t.className='toast show'+(error?' error':'');clearTimeout(state.toastTimer);state.toastTimer=setTimeout(()=>t.className='toast',4500);}
async function api(path,options={}){
  const controller=new AbortController(); const timer=setTimeout(()=>controller.abort(),10000);
  try{
    const response=await fetch(path,{...options,signal:controller.signal});
    const data=await response.json();
    if(!response.ok||!data.success)throw new Error(data.message||'Resposta invalida do Gateway');
    return data;
  }finally{clearTimeout(timer);}
}
function setConnection(connected){
  state.gateway=connected;const label=$('gateway-status');
  label.className='connection '+(connected?'online':'offline');
  label.innerHTML='<span class="status-light"></span>'+(connected?'Gateway conectado':'Gateway indisponível');
}
function statusPill(status){return (status||'OFFLINE').toUpperCase();}
function populateSelect(id,values,includeAll=false){
  const select=$(id), old=select.value;
  select.replaceChildren();
  if(includeAll){const opt=new Option('Todas as fontes','');select.add(opt);}
  for(const s of values){select.add(new Option(s.id,s.id));}
  if([...select.options].some(opt=>opt.value===old))select.value=old;
  else if(id==='history-source'||id==='control-source'){if([...select.options].some(x=>x.value==='FONTE_A'))select.value='FONTE_A';}
}
function renderSources(sources){
  state.sources=sources;
  $('total-sources').textContent=sources.length;
  $('online-sources').textContent=sources.filter(s=>s.status==='ONLINE').length;
  const a=sources.find(s=>s.id==='FONTE_A');
  $('temp-value').textContent=a&&a.status==='ONLINE'?format(a.temperature):'—';
  $('hum-value').textContent=a&&a.status==='ONLINE'?format(a.humidity):'—';
  $('last-update').textContent='Atualizado às '+new Date().toLocaleTimeString('pt-BR');
  const body=$('sources-body');body.replaceChildren();
  if(!sources.length){const tr=el('tr');const td=el('td','empty','Nenhuma fonte descoberta. Verifique NodeMCU, bridge e multicast.');td.colSpan=6;tr.append(td);body.append(tr);}
  for(const s of sources){
    const tr=el('tr');
    tr.append(el('td','',s.id),el('td','',s.kind.replaceAll('_',' ')));
    const status=el('td');status.append(el('span','status-tag '+s.status.toLowerCase(),statusPill(s.status)));tr.append(status);
    tr.append(el('td','',s.ip),el('td','',format(s.interval_ms/1000,1)+' s'));
    const ctrl=el('td');ctrl.append(el('span','pill '+(s.control_available?'':'muted'),s.control_available?'gRPC disponível':s.controllable?'Aguardando bridge':'Não controlável'));tr.append(ctrl);
    body.append(tr);
  }
  populateSelect('history-source',sources);
  populateSelect('aggregate-source',sources,true);
  populateSelect('control-source',sources.filter(s=>s.controllable));
  updateControlStatus();
}
async function refreshSources(silent=false){
  try{const data=await api('/api/sources');setConnection(true);renderSources(data.sources||[]);}
  catch(e){setConnection(false);if(!silent)toast(e.message,true);}
}
function updateControlStatus(){
  const src=state.sources.find(s=>s.id===val('control-source'));
  const ready=!!(src&&src.control_available);
  const label=$('control-availability');
  label.className='control-status '+(ready?'available':'');
  if(!src)label.textContent='Nenhuma fonte controlável detectada.';
  else if(!src.control_available)label.textContent='Bridge gRPC ainda não anunciado. Inicie fonte_a_bridge.bridge.';
  else if(src.status==='OFFLINE')label.textContent='Fonte offline; controle gRPC disponível para tentativa de recuperação.';
  else label.textContent=`${src.id} • ${src.status} • gRPC ${src.grpc_host}:${src.grpc_port} • ${src.ip}`;
  for(const id of ['btn-on','btn-off','btn-failure-on','btn-failure-off','btn-interval','btn-threshold'])$(id).disabled=!ready;
  if(src && state.lastControlSource !== src.id){$('interval-value').value=src.interval_ms||15000;}
  state.lastControlSource=src?.id||null;
}
async function command(kind,value){
  const source_id=val('control-source');if(!source_id)return toast('Selecione uma fonte',true);
  const names={enabled:'Ativação',failure:'Falha simulada',interval:'Intervalo',threshold:'Limiar'};
  const feedback=$('command-feedback');feedback.className='feedback';feedback.textContent=`Enviando ${names[kind]} à ${source_id}...`;
  try{
    const data=await api('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_id,command:kind,value})});
    feedback.className='feedback ok';feedback.textContent='✓ '+data.message;toast('Comando confirmado pelo serviço de controle.');
    await refreshSources(true);
  }catch(e){feedback.className='feedback error';feedback.textContent='✕ '+e.message;toast(e.message,true);}
}
function rangeY(points){let min=Math.min(...points),max=Math.max(...points);const gap=Math.max((max-min)*.16,1);return [min-gap,max+gap];}
function plotHistory(records){
  state.latestHistory=records;
  const canvas=$('history-canvas'),container=canvas.parentElement;
  const metric=val('history-metric');
  $('chart-empty').hidden=!!records.length;
  $('history-count').textContent=records.length+' amostra'+(records.length===1?'':'s');
  $('chart-series-name').textContent=metricLabels[metric];
  const width=container.clientWidth,height=container.clientHeight;
  if(width===0||height===0)return;
  const ratio=Math.min(window.devicePixelRatio||1,3);
  canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);
  const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);ctx.clearRect(0,0,width,height);
  const left=57,right=15,top=21,bottom=33,w=width-left-right,h=height-top-bottom;
  if(!records.length)return;
  const values=records.map(r=>r.value);
  const [min,max]=rangeY(values),time=records.map(r=>r.timestamp);
  const first=Math.min(...time),last=Math.max(...time);
  const x=t=>left+(last === first ? 0.5 : (t-first)/(last-first))*w;
  const y=v=>top+h-(v-min)/(max-min)*h;
  ctx.font='11px Segoe UI,Arial,sans-serif';ctx.textAlign='right';ctx.strokeStyle='#e6edf6';ctx.fillStyle='#91a0b4';ctx.lineWidth=1;
  for(let i=0;i<=4;i++){const yy=top+(h*i/4);ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(left+w,yy);ctx.stroke();ctx.fillText(format(max-i*(max-min)/4,1),left-9,yy+4);}
  ctx.textAlign='center';ctx.fillStyle='#9da9ba';
  for(let i=0;i<3;i++){const t=first+(last-first)*i/2;ctx.fillText(new Date(t*1000).toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit',second:'2-digit'}),left+i*w/2,height-12);}
  const sorted=records.toSorted?records.toSorted((a,b)=>a.timestamp-b.timestamp):[...records].sort((a,b)=>a.timestamp-b.timestamp);
  ctx.lineWidth=2.5;ctx.strokeStyle='#3478ed';ctx.lineJoin='round';ctx.beginPath();
  sorted.forEach((r,i)=>i===0?ctx.moveTo(x(r.timestamp),y(r.value)):ctx.lineTo(x(r.timestamp),y(r.value)));ctx.stroke();
  ctx.lineTo(x(sorted.at(-1).timestamp),top+h);ctx.lineTo(x(sorted[0].timestamp),top+h);ctx.closePath();ctx.fillStyle='rgba(52,120,237,.07)';ctx.fill();
  ctx.fillStyle='#3478ed';for(const p of sorted){ctx.beginPath();ctx.arc(x(p.timestamp),y(p.value),Math.min(3.2,Math.max(1.8,4-0.017*sorted.length)),0,2*Math.PI);ctx.fill();}
}
async function refreshHistory(silent=false){
  const source=val('history-source'),metric=val('history-metric');
  try{const query=new URLSearchParams({source_id:source,metric,limit:'100'});const data=await api('/api/history?'+query);
    plotHistory((data.readings||[]).sort((a,b)=>a.timestamp-b.timestamp));
  }catch(e){if(!silent)toast(e.message,true);}
}
async function aggregate(){
  const query=new URLSearchParams({source_id:val('aggregate-source'),metric:val('aggregate-metric'),operation:val('aggregate-op'),seconds:val('aggregate-window')});
  const box=$('aggregate-result');
  try{const data=await api('/api/aggregate?'+query);const r=data.aggregate;
    box.replaceChildren(el('div','small-label',opLabels[r.operation].toUpperCase()+' • '+metricLabels[r.metric]),el('div','aggregate-number',format(r.value,2)+' '+units[r.metric]),el('p','',r.samples+' amostras • '+(r.source||'Todas as fontes')));
  }catch(e){box.replaceChildren(el('div','small-label','RESULTADO'),el('div','aggregate-number','—'),el('p','',e.message));toast(e.message,true);}
}
$('refresh').addEventListener('click',async()=>{await refreshSources();await refreshHistory(true);});
$('history-refresh').addEventListener('click',()=>refreshHistory());
$('history-source').addEventListener('change',()=>refreshHistory(true));
$('history-metric').addEventListener('change',()=>refreshHistory(true));
$('run-aggregate').addEventListener('click',aggregate);
$('control-source').addEventListener('change',updateControlStatus);
$('btn-on').addEventListener('click',()=>command('enabled',true));
$('btn-off').addEventListener('click',()=>command('enabled',false));
$('btn-failure-on').addEventListener('click',()=>{if(confirm('Simular falha da fonte selecionada? Ela deixará de publicar leituras.'))command('failure',true);});
$('btn-failure-off').addEventListener('click',()=>command('failure',false));
$('btn-interval').addEventListener('click',()=>command('interval',Number(val('interval-value'))));
$('btn-threshold').addEventListener('click',()=>command('threshold',Number(val('threshold-value'))));
window.addEventListener('resize',()=>plotHistory(state.latestHistory));
async function refreshAll(){await refreshSources(true);if(state.gateway)await refreshHistory(true);}
refreshAll();setInterval(refreshAll,5000);
