const $ = (selector) => document.querySelector(selector);
const state = { mode: 'shared', dashboard: null, demo: false, offline: false, view: 'home' };
const text = (v) => String(v ?? '');
const esc = (v) => text(v).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dateLabel = (v) => v ? new Date(v*1000).toLocaleDateString('ko-KR', {month:'numeric',day:'numeric'}) : '기록 없음';
const ago = (v) => { if (!v) return '기록 없음'; const n = Math.max(0, Math.floor((Date.now()/1000-v)/86400)); return n === 0 ? '오늘' : n + '일 전'; };
const labels = {active:'활발',light:'가끔 참여',solo_only:'개인 활동만',no_matches:'게임 기록 없음',sync_issue:'조회 확인 필요'};
const modeNames = {shared:'같은 경기',total:'전체 게임',solo_duo:'솔로·듀오',shared_solo_duo:'회원끼리 솔·듀',shared_flex:'회원끼리 자랭',flex:'자유랭크',aram:'칼바람',normal:'일반',custom:'커스텀'};
function showToast(message) { const node = $('#toast'); node.textContent=message; node.classList.remove('hidden'); setTimeout(()=>node.classList.add('hidden'),3500); }
async function api(path, options = {}) {
  let response;
  try { response = await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})},credentials:'same-origin'}); }
  catch { throw new Error('서버에 연결할 수 없습니다. 운영 상태를 확인해주세요.'); }
  let payload = null;
  try { payload = await response.json(); } catch {}
  if (!response.ok) throw new Error(typeof payload?.detail === 'string' ? payload.detail : `요청 실패 (${response.status})`);
  return payload;
}
function selectScreen() {
  const wanted = (location.hash || '#home').slice(1);
  const view = ['home','ranking','members','how'].includes(wanted) ? wanted : 'home';
  state.view=view;
  document.querySelectorAll('[data-screen]').forEach(node => node.classList.toggle('hidden', node.dataset.screen!==view));
  document.querySelectorAll('.topnav a[data-nav]').forEach(node => node.classList.toggle('on',node.dataset.nav===view));
  document.title = ({home:'홈',ranking:'모임 랭킹',members:'회원 활동',how:'운영 안내'}[view]) + ' | ROLLU';
  if(view==='members' && state.dashboard)renderMembers();
  window.scrollTo(0,0);
}
function render() {
  const data = state.dashboard;
  if (!data) return;
  $('#currentMonthLabel').textContent = data.month ? data.month.replace('-', '년 ') + '월' : '이번 달';
  $('#statMembers').textContent = data.summary.members;
  $('#statActive').textContent = data.summary.active;
  $('#statLight').textContent = data.summary.light;
  $('#statNoClub').textContent = data.summary.no_club;
  const sync = data.sync;
  $('#syncText').textContent = state.demo ? '가상 데이터 · 자동 연동 미설정' : sync.running ? '현재 자동 전적 동기화 중…' : sync.last_finished ? `마지막 동기화 ${dateLabel(sync.last_finished)}` : '실제 전적 동기화 대기 중';
  $('#activityRule').textContent = data.rule + ' 동기화 오류 회원은 조회 확인 필요로 표시합니다.';
  const statValue = (p) => ['shared_solo_duo','shared_flex'].includes(state.mode) ? (p.shared_by_mode[state.mode.slice(7)] || 0) : ['solo_duo','flex','aram','normal'].includes(state.mode) ? (p.by_mode[state.mode] || 0) : state.mode==='total' ? p.total : state.mode==='custom' ? p.custom : p.shared;
  $('#rankingList').innerHTML = data.members.length ? data.members.map((p,i)=>`<div class="rank-row ${i===0?'top':i===1?'rank-two':i===2?'rank-three':''}">
    <div class="rank-num ${i<3?'medal':''}">${i===0?'🥇':i===1?'🥈':i===2?'🥉':i+1}</div>
    <div class="rank-user"><div class="avatar">${esc(p.nickname.slice(0,1))}</div><div style="min-width:0"><div class="user-name">${esc(p.nickname)}</div><div class="riot-name">${esc(p.riot_id)}</div></div></div>
    <div class="rank-extra">승률 ${p.win_rate===null?'—':p.win_rate+'%'}<small>최근 플레이 ${esc(ago(p.last_played_at))}</small></div>
    <div class="rank-stat">${statValue(p).toLocaleString()}<span>판 · ${esc(modeNames[state.mode])}</span></div></div>`).join('') : `<div class="loading">아직 승인된 회원이 없어요. 회원을 등록하고 운영진이 승인하면 표시됩니다.</div>`;
  renderMembers();
}
function renderMembers() {
  if (!state.dashboard) return;
  const key = $('#memberSearch').value.trim().toLowerCase();
  const members = state.dashboard.members.filter(p=>p.nickname.toLowerCase().includes(key)||p.riot_id.toLowerCase().includes(key));
  $('#membersBody').innerHTML = members.length ? members.map(p=>`<tr><td>${esc(p.nickname)}<span class="small-id">${esc(p.riot_id)} · 함께한 회원: ${esc((p.partners||[]).slice(0,3).map(x=>x.nickname+' '+x.games+'판').join(', ') || '확인되지 않음')}</span></td><td><span class="status ${esc(p.status)}">${esc(labels[p.status]||p.status)}</span></td><td>${p.shared}판</td><td>${p.shared_by_mode?.solo_duo||0}판</td><td>${p.shared_by_mode?.flex||0}판</td><td>${p.total}판</td><td>${esc(ago(p.last_played_at))}</td></tr>`).join('') : `<tr><td colspan="7" class="loading">해당 회원을 찾지 못했어요.</td></tr>`;
}
async function load() {
  try { state.dashboard = await api(`/api/dashboard?mode=${encodeURIComponent(state.mode)}`); render(); }
  catch(e) { $('#rankingList').innerHTML = `<div class="loading">${esc(e.message)}</div>`; }
}
function openModal(title, html) { $('#modalTitle').textContent=title; $('#modalBody').innerHTML=html; $('#modalBackdrop').classList.remove('hidden'); document.body.style.overflow='hidden'; }
function closeModal() { $('#modalBackdrop').classList.add('hidden'); document.body.style.overflow=''; }
function setError(message) { const el = $('#formError'); if(el) el.textContent=message; }
function accessModal() {
  openModal('롤루 모임 전용',`<p class="form-help">이 사이트는 롤루 회원만 열람할 수 있어요. 운영진에게 받은 <b>모임 열람 코드</b>를 입력하면 이 브라우저에서 30일간 활동 현황을 볼 수 있습니다.</p><form id="accessForm"><label class="form-field">모임 열람 코드<input type="password" name="code" required autocomplete="off" placeholder="운영진이 알려준 코드"></label><button type="submit" class="btn primary full">모임 기록 보기</button><p class="form-error" id="formError"></p></form>`);
  $('#accessForm').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/viewer/login',{method:'POST',body:JSON.stringify({code:new FormData(e.currentTarget).get('code')})});closeModal();await load();}catch(err){setError(err.message);}});
}
function joinModal() {
  openModal('롤루 회원 등록',`<p class="form-help">처음 한 번만 등록하면 운영진 확인 후 자동 전적 집계가 시작돼요. 라이엇 ID는 게임 이름과 # 뒤 태그를 나눠 적어주세요.</p>
  <form id="joinForm"><label class="form-field">모임에서 사용할 이름<input name="nickname" maxlength="24" required placeholder="예: 파랑별" autocomplete="off"></label>
  <div class="two-input"><label class="form-field">라이엇 게임 이름<input name="game_name" required maxlength="32" placeholder="게임 이름" autocomplete="off"></label><label class="form-field">태그 (# 제외)<input name="tag_line" required maxlength="8" placeholder="KR1" autocomplete="off"></label></div>
  <label class="form-field">모임 초대 코드<input name="join_code" type="password" required placeholder="운영진에게 받은 코드" ${state.demo?'value="demo"':''}></label>
  <label class="consent"><input type="checkbox" name="consent_public" required><span><b>[필수]</b> 라이엇 ID와 공개 경기의 게임 수·승률·회원 간 같은 경기 기록을 모임원에게 표시하고, 탈퇴 후에는 운영진이 이전 월 기록을 보관 기간 동안 열람할 수 있음에 동의합니다. 삭제 요청 시 관련 기록이 파기됩니다.</span></label>
  <label class="consent"><input type="checkbox" name="consent_custom"><span><b>[선택]</b> 사용자 설정 게임(비공개 내전 포함)이 API로 제공될 경우, 내 해당 경기 기록을 모임에 표시하는 데 별도로 동의합니다.</span></label>
  <p class="form-help">※ 소유권 확인용 Riot 공식 로그인(RSO)은 승인 전이므로 운영진이 당사자임을 확인해야 합니다. 타인 계정을 대신 등록하지 마세요.</p>
  <button class="btn primary full" type="submit">회원 등록 신청</button><p class="form-error" id="formError"></p></form>`);
  if(state.offline) {
    const button=$('#joinForm').querySelector('[type=submit]');
    button.disabled=true;
    button.textContent='미리보기에서는 신청할 수 없어요';
    setError('실제 회원 등록은 ZIP 파일의 서버를 실행한 후 이용할 수 있어요.');
  }
  $('#joinForm').addEventListener('submit',async e=>{
    e.preventDefault(); const f=new FormData(e.currentTarget); const btn=e.currentTarget.querySelector('button[type=submit]'); btn.disabled=true;
    try { const r=await api('/api/join',{method:'POST',body:JSON.stringify({nickname:f.get('nickname'),game_name:f.get('game_name'),tag_line:f.get('tag_line'),join_code:f.get('join_code'),consent_public:!!f.get('consent_public'),consent_custom:!!f.get('consent_custom')})});
      openModal('가입 신청 완료',`<p>운영진이 회원을 확인하고 승인하면 자동 집계가 시작됩니다.</p><p class="form-help"><b>아래 관리 토큰을 반드시 저장하세요.</b> 이후 내전 동의를 철회하거나 본인 데이터를 삭제할 때 필요합니다. 서버는 토큰 원문을 다시 보여주지 않습니다.</p><div class="token-box" id="myToken">${esc(r.management_token)}</div><button class="btn primary full" id="copyToken">관리 토큰 복사</button><p class="form-help">이 시스템은 아직 라이엇 계정 소유권을 자동 인증하지 않습니다.</p>`);
      $('#copyToken').addEventListener('click', async()=>{try{await navigator.clipboard.writeText(r.management_token);showToast('관리 토큰을 복사했어요.');}catch{showToast('토큰을 길게 눌러 복사해 주세요.');}});
    } catch(err){ setError(err.message); btn.disabled=false; }
  });
}
function manageModal(){
  openModal('내 정보 관리',`<p class="form-help">회원 등록 당시 받은 개인 관리 토큰을 입력하세요. 해당 토큰으로 커스텀 게임 기록 공개 동의를 철회하거나 모든 등록 정보를 삭제할 수 있습니다.</p>
  <label class="form-field">개인 관리 토큰<input id="manageToken" type="password" placeholder="등록할 때 받은 토큰"></label>
  <label class="consent"><input id="customConsent" type="checkbox"><span>커스텀/내전 기록 공개에 동의 (해제하면 기존 사용자 설정 게임 기록도 삭제)</span></label>
  <button class="btn outline full" id="saveConsent">동의 상태 저장</button><button class="btn full" id="deleteSelf" style="color:#ffa5a5;background:#301f2c">내 기록·회원정보 전체 삭제</button><p class="form-error" id="formError"></p>`);
  if(state.offline) {
    $('#saveConsent').disabled=true;
    $('#deleteSelf').disabled=true;
    setError('미리보기에서는 정보 변경·삭제를 실행하지 않아요.');
  }
  $('#saveConsent').addEventListener('click',async()=>{try {await api('/api/me/consent',{method:'POST',body:JSON.stringify({token:$('#manageToken').value,consent_custom:$('#customConsent').checked})});showToast('동의 상태를 변경했어요.');closeModal();await load();}catch(e){setError(e.message);}});
  $('#deleteSelf').addEventListener('click',async()=>{if(!confirm('모임 기록과 회원 정보를 영구 삭제할까요?'))return;try{await api('/api/me/delete',{method:'POST',body:JSON.stringify({token:$('#manageToken').value})});closeModal();await load();showToast('회원 정보가 삭제되었습니다.');}catch(e){setError(e.message);}});
}
function adminModal() {
  openModal('운영진 로그인',`<p class="form-help">운영진만 회원을 승인하거나 삭제하고 전적 재수집을 실행할 수 있어요.</p><form id="loginForm"><label class="form-field">운영진 비밀번호<input type="password" name="password" required placeholder="운영진 비밀번호" autocomplete="current-password"></label><button class="btn primary full" type="submit">로그인</button><p class="form-error" id="formError"></p></form>`);
  $('#loginForm').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/admin/login',{method:'POST',body:JSON.stringify({password:new FormData(e.currentTarget).get('password')})});await adminPanel();}catch(err){setError(err.message);}});
}
async function adminPanel() {
  try {
    const [r, history] = await Promise.all([api('/api/admin/members'),api('/api/admin/months')]);
    const pending=r.members.filter(x=>!x.approved && x.active), approved=r.members.filter(x=>x.approved && x.active), departed=r.members.filter(x=>!x.active && x.approved);
    openModal('운영진 · 회원 및 월별 기록',`<p class="form-help">가입 신청 ${pending.length}건 · 활동 회원 ${approved.length}명 · 탈퇴 처리 ${departed.length}명. 탈퇴 처리는 기존 전적을 보관하고 <b>새 전적 수집만 중단</b>합니다.</p>
    <h3>📅 월별 기록 조회</h3><label class="form-field">과거 월 선택<select id="adminHistoryMonth" class="admin-select">${history.months.map(m=>`<option value="${esc(m)}">${esc(m)} (${m===history.current?'이번 달':'지난 기록'})</option>`).join('')}</select></label>
    <div id="adminMonthlyReport" class="history-panel">월별 통계를 불러오는 중...</div>
    <h3>승인 대기</h3><div>${pending.length? pending.map(x=>`<div class="admin-member"><div><b>${esc(x.nickname)}</b><small>${esc(x.game_name)}#${esc(x.tag_line)}</small></div><div><button class="small-btn" data-approve="${x.id}">승인</button> <button class="small-btn warn" data-purge="${x.id}">거절</button></div></div>`).join(''):'<p class="form-help">대기 중인 신청이 없습니다.</p>'}</div>
    <h3>현재 모임원</h3><div style="max-height:220px;overflow:auto">${approved.map(x=>`<div class="admin-member"><div><b>${esc(x.nickname)}</b><small>${esc(x.game_name)}#${esc(x.tag_line)} · ${x.last_sync_error?'수집 오류':x.last_sync_at?'수집 완료':'수집 대기'}</small></div><button class="small-btn warn" data-leave="${x.id}">탈퇴 처리</button></div>`).join('')||'<p class="form-help">아직 회원이 없습니다.</p>'}</div>
    <h3>탈퇴 처리된 회원</h3><div style="max-height:170px;overflow:auto">${departed.map(x=>`<div class="admin-member"><div><b>${esc(x.nickname)}</b><small>탈퇴 상태 · 과거 기록 보관</small></div><div><button class="small-btn" data-reactivate="${x.id}">재가입 복구</button> <button class="small-btn warn" data-purge="${x.id}">완전 삭제</button></div></div>`).join('')||'<p class="form-help">탈퇴 처리된 회원이 없습니다.</p>'}</div>
    <button class="btn primary full" id="runSync">현재 회원 전적 갱신 요청</button><button class="btn subtle full" id="logout">운영진 로그아웃</button><p class="form-error" id="formError"></p>`);
    async function fetchHistory() {
      const month=$('#adminHistoryMonth').value;
      const box=$('#adminMonthlyReport'); box.textContent='조회 중...';
      try {
        const data=await api(`/api/admin/dashboard?month=${encodeURIComponent(month)}&mode=shared`);
        const rows=data.members;
        box.innerHTML=`<div class="history-meta"><b>${esc(month)} 월간 활동 현황</b><span>${rows.length}명 · 모임 게임 기록 기준</span></div>
          <div class="history-scroll"><table class="history-table"><thead><tr><th>회원</th><th>같은 팀</th><th>솔·듀 함께</th><th>자랭 함께</th><th>전체 게임</th></tr></thead><tbody>${rows.map(p=>`<tr><td>${esc(p.nickname)}${p.is_left?' <small>(탈퇴)</small>':''}</td><td>${p.shared}</td><td>${p.shared_by_mode?.solo_duo||0}</td><td>${p.shared_by_mode?.flex||0}</td><td>${p.total}</td></tr>`).join('')||'<tr><td colspan="5">기록 없음</td></tr>'}</tbody></table></div><p class="form-help">해당 월에 활동했던 회원을 포함합니다. API 미수집·등록 전 경기는 누락될 수 있습니다.</p>`;
      } catch(err) {box.textContent=err.message;}
    }
    $('#adminHistoryMonth').addEventListener('change',fetchHistory);
    await fetchHistory();
    if(state.offline){
      const label=document.createElement('p');
      label.className='form-help';
      label.textContent='[화면 체험용] 지난달 조회는 가능하지만 승인·탈퇴·삭제·전적 갱신은 작동하지 않습니다. 실제 기능은 서버를 실행해야 합니다.';
      $('#modalBody').prepend(label);
      document.querySelectorAll('[data-approve],[data-leave],[data-reactivate],[data-purge],#runSync').forEach(button=>{
        button.disabled=true;
        button.title='오프라인 미리보기에서는 실행할 수 없습니다';
      });
      $('#logout').textContent='닫기';
    }
    document.querySelectorAll('[data-approve]').forEach(b=>b.addEventListener('click',async()=>{try{await api(`/api/admin/members/${b.dataset.approve}/approve`,{method:'POST'});await adminPanel();await load();}catch(e){setError(e.message);}}));
    document.querySelectorAll('[data-leave]').forEach(b=>b.addEventListener('click',async()=>{if(!confirm('모임에서 탈퇴 처리하고 새 전적 수집을 중단할까요? 과거 월 기록은 보관됩니다.'))return;try{await api(`/api/admin/members/${b.dataset.leave}/leave`,{method:'POST'});await adminPanel();await load();}catch(e){setError(e.message);}}));
    document.querySelectorAll('[data-reactivate]').forEach(b=>b.addEventListener('click',async()=>{try{await api(`/api/admin/members/${b.dataset.reactivate}/reactivate`,{method:'POST'});await adminPanel();await load();}catch(e){setError(e.message);}}));
    document.querySelectorAll('[data-purge]').forEach(b=>b.addEventListener('click',async()=>{if(!confirm('이 회원과 관련 전적 데이터를 영구 삭제할까요? 과거 월 기록에서도 사라집니다.'))return;try{await api(`/api/admin/members/${b.dataset.purge}`,{method:'DELETE'});await adminPanel();await load();}catch(e){setError(e.message);}}));
    $('#runSync').addEventListener('click',async()=>{try{const r=await api('/api/admin/sync',{method:'POST'});showToast(r.message);}catch(e){setError(e.message);}});
    $('#logout').addEventListener('click',async()=>{
      if(state.offline){closeModal();return;}
      try{await api('/api/admin/logout',{method:'POST'});closeModal();showToast('로그아웃했습니다.');}catch(e){setError(e.message);}
    });
  } catch(err) { adminModal(); }
}
async function init() {
  state.offline=Boolean(window.ROLLU_OFFLINE_PREVIEW);
  selectScreen();
  window.addEventListener('hashchange',selectScreen);
  try { const config=await api('/api/config');state.demo=!!config.demo;if(state.demo)$('#demoBar').classList.remove('hidden'); }
  catch(e) {showToast(e.message);}
  document.querySelectorAll('[data-mode]').forEach(chip=>chip.addEventListener('click',async()=>{state.mode=chip.dataset.mode;document.querySelectorAll('[data-mode]').forEach(x=>x.classList.toggle('active',x===chip));await load();}));
  $('#memberSearch').addEventListener('input',renderMembers);
  $('#joinBtn').addEventListener('click',joinModal);
  $('#manageBtn').addEventListener('click',manageModal);
  $('#adminBtn').addEventListener('click',async()=>{try{await api('/api/admin/members');await adminPanel();}catch{adminModal();}});
  $('#modalClose').addEventListener('click',closeModal);
  $('#modalBackdrop').addEventListener('click',e=>{if(e.target===$('#modalBackdrop'))closeModal();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
  await load();
}
init();
