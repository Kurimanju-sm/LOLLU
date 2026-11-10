"""One-file offline front-end preview. NO API key, accounts or live Riot traffic."""
import os, json
from pathlib import Path
os.environ['DEMO_MODE']='1'
os.environ['DATABASE_PATH']=os.environ.get('DATABASE_PATH',str(Path(__file__).parent / 'preview_build.sqlite3'))
from app.db import init_db,session
from app.main import seed_demo
from app.service import dashboard,current_month,add_month,historic_months
BASE=Path(__file__).parent
init_db(); seed_demo()
modes=['shared','shared_solo_duo','shared_flex','total','solo_duo','flex','aram','normal','custom']
store={mode:dashboard(mode=mode,month=current_month()) for mode in modes}
archive={month:dashboard(mode='shared',month=month,include_left=True) for month in historic_months()}
with session() as c:
    members=[dict(x) for x in c.execute('''SELECT id,nickname,game_name,tag_line,joined_at,approved,active,left_at,consent_custom,last_sync_at,last_sync_error FROM members ORDER BY id''')]
html=(BASE/'app/static/index.html').read_text()
css=(BASE/'app/static/style.css').read_text()
js=(BASE/'app/static/app.js').read_text()
html=html.replace('<link rel="stylesheet" href="/static/style.css" />',f'<style>{css}</style>')
html=html.replace('<link rel="icon" type="image/svg+xml" href="/static/logo.svg" />','')
html=html.replace('  <script defer src="/static/app.js"></script>','')
mockjs='''
// OFFLINE PREVIEW: completely simulated responses; no network and no Riot credentials.
window.ROLLU_OFFLINE_PREVIEW = true;
const previewData = ''' + json.dumps({'store':store,'archive':archive,'members':members,'months':historic_months(),'current':current_month()},ensure_ascii=False,separators=(',',':')) + ''';
const previewJson=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'content-type':'application/json'}});
window.fetch=async function(input, options={}) {
 const u=new URL(String(input),'https://rollu.local');
 if (u.pathname==='/api/config') return previewJson({demo:true,api_configured:false});
 if (u.pathname==='/api/dashboard') return previewJson(previewData.store[u.searchParams.get('mode')||'shared']||previewData.store.shared);
 if (u.pathname==='/api/admin/members') return previewJson({members:previewData.members});
 if (u.pathname==='/api/admin/months') return previewJson({months:previewData.months,current:previewData.current,timezone:'Asia/Seoul'});
 if (u.pathname==='/api/admin/dashboard') return previewJson(previewData.archive[u.searchParams.get('month')]||previewData.archive[previewData.current]);
 if (u.pathname==='/api/admin/login') return previewJson({ok:true});
 return previewJson({detail:'오프라인 가상 데이터 미리보기에서는 가입·수정·탈퇴·동기화를 실행할 수 없습니다. ZIP 속 서버판을 사용하세요.'},503);
};
'''
html=html.replace('</body>',f'<script>{mockjs}</script><script>{js}</script></body>')
html=html.replace('DEMO MODE</strong> 이 페이지의 회원·전적은 모두 테스트용 가상 데이터입니다. 실제 라이엇 API와 연결되어 있지 않아요.', '화면 미리보기</strong> 메뉴와 월별 기록은 직접 둘러볼 수 있어요. 회원 등록·탈퇴·자동 수집은 서버를 실행해야 합니다. 표시되는 회원은 가상 데이터예요.')
(BASE/'ROLLU_오프라인_미리보기.html').write_text(html)
print((BASE/'ROLLU_오프라인_미리보기.html').stat().st_size)
