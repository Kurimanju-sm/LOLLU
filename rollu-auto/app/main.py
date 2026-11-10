"""ROLLU: opt-in LoL activity dashboard, NOT an unofficial skill MMR service."""
import asyncio
import hashlib
import hmac
import os
import random
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, Request, Response, Cookie, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .db import init_db, session
from .riot import RiotClient, RiotError
from .service import dashboard, sync_all, current_month, historic_months

BASE = Path(__file__).parent
DEMO = os.getenv("DEMO_MODE", "0") == "1"

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def get_admin_password():
    return os.getenv("ADMIN_PASSWORD", "")

def check_origin(req: Request):
    # Combined with SameSite cookies + JSON body, blocks cross-origin form mutations.
    origin = req.headers.get("origin")
    if origin and not origin.endswith("//" + req.headers.get("host", "")):
        raise HTTPException(403,"요청 출처를 확인할 수 없습니다.")

def admin_auth(rollu_admin: str | None = Cookie(default=None)):
    if not rollu_admin: raise HTTPException(401,"운영진 로그인이 필요합니다.")
    with session() as c:
        row = c.execute("SELECT expires_at FROM admin_sessions WHERE token_hash=?", (digest(rollu_admin),)).fetchone()
    if not row or row["expires_at"] < time.time(): raise HTTPException(401,"운영진 로그인 세션이 만료되었습니다.")
    return True

class JoinRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=24)
    game_name: str = Field(min_length=2, max_length=32)
    tag_line: str = Field(min_length=2, max_length=8)
    join_code: str = Field(min_length=1, max_length=100)
    consent_public: bool
    consent_custom: bool = False

class LoginRequest(BaseModel):
    password: str

class ViewCodeRequest(BaseModel):
    code: str

class UpdateConsent(BaseModel):
    token: str
    consent_custom: bool

class DeleteSelf(BaseModel):
    token: str

async def sync_loop(app):
    while True:
        try:
            # Trigger on schedule or admin approval.
            interval = max(15,int(os.getenv("SYNC_INTERVAL_MINUTES","180"))) * 60
            try:
                await asyncio.wait_for(app.state.refresh_event.wait(),timeout=interval)
            except asyncio.TimeoutError: pass
            app.state.refresh_event.clear()
            if not DEMO and app.state.riot.api_key:
                async with app.state.sync_lock:
                    await sync_all(app.state.riot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print("ROLLU sync failed:",type(exc).__name__,str(exc)[:180])

@asynccontextmanager
async def lifespan(app):
    if not DEMO:
        if get_admin_password() in ("", "CHANGE_THIS_TO_A_LONG_RANDOM_PASSWORD"):
            raise RuntimeError(".env의 ADMIN_PASSWORD를 안전한 임의 비밀번호로 설정하세요.")
        if os.getenv("JOIN_CODE", "") in ("", "CHANGE_THIS_TO_A_DIFFERENT_RANDOM_JOIN_CODE"):
            raise RuntimeError(".env의 JOIN_CODE를 안전한 임의 초대 코드로 설정하세요.")
    init_db()
    if DEMO: seed_demo()
    app.state.riot = RiotClient()
    app.state.refresh_event = asyncio.Event()
    app.state.sync_lock = asyncio.Lock()
    task = asyncio.create_task(sync_loop(app))
    try: yield
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        await app.state.riot.close()

app = FastAPI(title="ROLLU Club", version="1.1.0", lifespan=lifespan)
app.mount("/static",StaticFiles(directory=str(BASE / "static")),name="static")

@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")

@app.get("/api/config")
def config():
    return {"demo":DEMO,"api_configured":bool(os.getenv("RIOT_API_KEY")),"read_only_public":True,"name":"ROLLU","disclaimer":"모임 참여는 동일 경기/팀을 기준으로 추정하며 라이엇 공식 MMR이 아닙니다."}

def viewer_auth(rollu_viewer: str | None = Cookie(default=None), rollu_admin: str | None = Cookie(default=None)):
    if DEMO: return True
    now = int(time.time())
    with session() as c:
        if rollu_admin and c.execute("SELECT 1 FROM admin_sessions WHERE token_hash=? AND expires_at>?", (digest(rollu_admin),now)).fetchone():
            return True
        if rollu_viewer and c.execute("SELECT 1 FROM viewer_sessions WHERE token_hash=? AND expires_at>?", (digest(rollu_viewer),now)).fetchone():
            return True
    raise HTTPException(401,"롤루 모임 전용 열람 코드가 필요합니다.")

@app.post("/api/viewer/login")
def viewer_login(body:ViewCodeRequest,req:Request,response:Response):
    check_origin(req)
    expected=os.getenv("VIEW_CODE") or os.getenv("JOIN_CODE","")
    if not DEMO and (not expected or not hmac.compare_digest(body.code,expected)):
        raise HTTPException(401,"모임 열람 코드가 일치하지 않습니다.")
    token=secrets.token_urlsafe(40)
    with session() as c:
        c.execute("DELETE FROM viewer_sessions WHERE expires_at<?",(int(time.time()),))
        c.execute("INSERT INTO viewer_sessions(token_hash,expires_at) VALUES(?,?)",(digest(token),int(time.time())+30*86400))
    response.set_cookie("rollu_viewer",token,httponly=True,secure=os.getenv("COOKIE_SECURE","0")=="1",samesite="lax",max_age=30*86400)
    return {"ok":True}

@app.get("/api/dashboard")
def get_dashboard(days:int=30, mode:str="shared",_=Depends(viewer_auth)):
    # All members see only the current KST calendar month, not private archives.
    return dashboard(mode=mode,month=current_month())

@app.post("/api/join",status_code=201)
async def join(form: JoinRequest, request: Request):
    check_origin(request)
    code = os.getenv("JOIN_CODE", "")
    if not DEMO and not hmac.compare_digest(form.join_code,code):
        raise HTTPException(403,"초대 코드가 올바르지 않습니다.")
    if not form.consent_public:
        raise HTTPException(422,"회원 공개 전적/활동 통계 처리 동의가 필요합니다.")
    if "#" in form.game_name or "#" in form.tag_line:
        raise HTTPException(422,"라이엇 ID와 태그를 각각 입력해 주세요.")
    if DEMO:
        puuid = "demo-new-" + secrets.token_hex(10)
        ri = {"gameName":form.game_name,"tagLine":form.tag_line,"puuid":puuid}
    else:
        try: ri = await request.app.state.riot.lookup(form.game_name.strip(),form.tag_line.strip())
        except RiotError as exc:
            raise HTTPException(502,str(exc))
    token = secrets.token_urlsafe(32)
    with session() as c:
        existing = c.execute("SELECT 1 FROM members WHERE puuid=?", (ri["puuid"],)).fetchone()
        if existing: raise HTTPException(409,"이미 등록된 라이엇 ID입니다. 운영진에게 문의해 주세요.")
        c.execute("""INSERT INTO members(nickname,game_name,tag_line,puuid,joined_at,approved,consent_public,consent_custom,access_token_hash)
            VALUES(?,?,?,?,?,0,1,?,?)""", (form.nickname.strip(),ri.get("gameName",form.game_name),ri.get("tagLine",form.tag_line),ri["puuid"],int(time.time()),int(form.consent_custom),digest(token)))
    return {"message":"가입 신청 완료. 운영진 승인 후 자동 수집됩니다.","management_token":token,"warning":"이 토큰은 재발급하지 않습니다. 안전한 곳에 보관하세요. 라이엇 계정 소유권 검증(RSO)은 미구현 상태입니다."}

@app.post("/api/me/consent")
def my_consent(body:UpdateConsent, request:Request):
    check_origin(request)
    with session() as c:
        row = c.execute("SELECT id,puuid FROM members WHERE access_token_hash=?", (digest(body.token),)).fetchone()
        if not row: raise HTTPException(401,"관리 토큰이 올바르지 않습니다.")
        c.execute("UPDATE members SET consent_custom=? WHERE id=?",(int(body.consent_custom),row["id"]))
        if not body.consent_custom:
            c.execute("DELETE FROM match_players WHERE puuid=? AND match_id IN (SELECT match_id FROM matches WHERE queue_id=0)",(row["puuid"],))
    return {"ok":True}

@app.post("/api/me/delete")
def my_delete(body:DeleteSelf, request:Request):
    check_origin(request)
    with session() as c:
        row=c.execute("SELECT id,puuid FROM members WHERE access_token_hash=?",(digest(body.token),)).fetchone()
        if not row: raise HTTPException(401,"관리 토큰이 올바르지 않습니다.")
        c.execute("DELETE FROM match_players WHERE puuid=?",(row["puuid"],))
        c.execute("DELETE FROM members WHERE id=?",(row["id"],))
        c.execute("DELETE FROM matches WHERE NOT EXISTS(SELECT 1 FROM match_players WHERE match_players.match_id=matches.match_id)")
    return {"ok":True}

@app.post("/api/admin/login")
def admin_login(body:LoginRequest,req:Request,response:Response):
    check_origin(req)
    expected=get_admin_password()
    if not expected or not hmac.compare_digest(body.password,expected):
        raise HTTPException(401,"비밀번호가 일치하지 않습니다.")
    token=secrets.token_urlsafe(40)
    expire=int(time.time())+8*3600
    with session() as c:
        c.execute("DELETE FROM admin_sessions WHERE expires_at<?",(int(time.time()),))
        c.execute("INSERT INTO admin_sessions(token_hash,expires_at) VALUES(?,?)",(digest(token),expire))
    response.set_cookie("rollu_admin",token,httponly=True,secure=os.getenv("COOKIE_SECURE","0")=="1",samesite="lax",max_age=8*3600)
    return {"ok":True}

@app.post("/api/admin/logout")
def admin_logout(req:Request,response:Response,_=Depends(admin_auth)):
    check_origin(req)
    token=req.cookies.get("rollu_admin")
    with session() as c:
        c.execute("DELETE FROM admin_sessions WHERE token_hash=?",(digest(token),))
    response.delete_cookie("rollu_admin")
    return {"ok":True}

@app.get("/api/admin/members")
def get_pending(_=Depends(admin_auth)):
    with session() as c:
        members=[dict(x) for x in c.execute("""SELECT id,nickname,game_name,tag_line,joined_at,approved,active,left_at,consent_custom,last_sync_at,last_sync_error FROM members ORDER BY active DESC, approved ASC, joined_at DESC""")]
    return {"members":members}

@app.post("/api/admin/members/{member_id}/approve")
def approve(member_id:int,req:Request,_=Depends(admin_auth)):
    check_origin(req)
    with session() as c:
        c.execute("UPDATE members SET approved=1 WHERE id=? AND active=1",(member_id,))
        if not c.execute("SELECT 1 FROM members WHERE id=?",(member_id,)).fetchone(): raise HTTPException(404,"회원 없음")
    req.app.state.refresh_event.set()
    return {"ok":True,"note":"라이엇 계정 실제 소유자인지 별도 확인 후 승인해야 합니다."}

@app.get("/api/admin/months")
def admin_months(_=Depends(admin_auth)):
    return {"months": historic_months(), "current": current_month(), "timezone":"Asia/Seoul"}

@app.get("/api/admin/dashboard")
def admin_monthly_dashboard(month:str, mode:str="shared", _=Depends(admin_auth)):
    if month not in historic_months():
        raise HTTPException(422,"조회할 수 있는 보관 월이 아닙니다.")
    return dashboard(mode=mode,month=month,include_left=True)

@app.post("/api/admin/members/{member_id}/leave")
def leave_member(member_id:int,req:Request,_=Depends(admin_auth)):
    """Hide from current roster and stop syncing; preserve prior months for admin archive."""
    check_origin(req)
    with session() as c:
        row=c.execute("SELECT id,approved,active FROM members WHERE id=?",(member_id,)).fetchone()
        if not row: raise HTTPException(404,"회원 없음")
        if not row['approved']: raise HTTPException(409,"가입 대기 회원은 거절하거나 삭제하세요.")
        c.execute("UPDATE members SET active=0,left_at=? WHERE id=? AND active=1",(int(time.time()),member_id))
    return {"ok":True,"message":"탈퇴 처리했습니다. 전적 자동 수집을 중단하고 지난달 기록은 보관합니다."}

@app.post("/api/admin/members/{member_id}/reactivate")
def reactivate_member(member_id:int,req:Request,_=Depends(admin_auth)):
    check_origin(req)
    with session() as c:
        row=c.execute("SELECT id,approved,active FROM members WHERE id=?",(member_id,)).fetchone()
        if not row: raise HTTPException(404,"회원 없음")
        if not row['approved']: raise HTTPException(409,"기존 승인 회원이 아닙니다.")
        c.execute("UPDATE members SET active=1,left_at=NULL,last_sync_at=NULL,last_sync_error=NULL WHERE id=?",(member_id,))
    req.app.state.refresh_event.set()
    return {"ok":True,"message":"재활성화했습니다. 다시 자동 수집합니다."}

@app.delete("/api/admin/members/{member_id}")
def remove_member(member_id:int,req:Request,_=Depends(admin_auth)):
    check_origin(req)
    with session() as c:
        row=c.execute("SELECT puuid FROM members WHERE id=?",(member_id,)).fetchone()
        if not row: raise HTTPException(404,"회원 없음")
        c.execute("DELETE FROM match_players WHERE puuid=?",(row["puuid"],))
        c.execute("DELETE FROM members WHERE id=?",(member_id,))
        c.execute("DELETE FROM matches WHERE NOT EXISTS(SELECT 1 FROM match_players WHERE match_players.match_id=matches.match_id)")
    return {"ok":True}

@app.post("/api/admin/sync")
def trigger_sync(req:Request,_=Depends(admin_auth)):
    check_origin(req)
    if DEMO: return {"ok":False,"message":"체험 모드는 가상 전적입니다. 실제 동기화가 실행되지 않습니다."}
    req.app.state.refresh_event.set()
    return {"ok":True,"message":"자동 동기화 작업을 예약했습니다. 실제 전적 갱신은 API 호출량에 따라 지연됩니다."}


def seed_demo():
    """Clearly labeled synthetic seed for UI testing; never show as actual Riot data."""
    rng=random.Random(174)
    now=int(time.time())
    names=["파랑별","초코구름","라면왕","별사탕","흰곰","우주펭귄","밤하늘","귤껍질","고양이발","쏘쿨","감자칩","작은용"]
    with session() as c:
        if c.execute("SELECT COUNT(*) FROM members").fetchone()[0]: return
        for i,name in enumerate(names):
            c.execute("""INSERT INTO members(nickname,game_name,tag_line,puuid,joined_at,approved,consent_public,consent_custom,access_token_hash,last_sync_at,first_sync_at)
            VALUES(?,?,?,?,?,1,1,1,?,?,?)""",(name,name,"KR1",f"synthetic-demo-{i}",now-90*86400,digest(f"demo-{i}"),now-300,now-90*86400))
        members=[dict(x) for x in c.execute("SELECT puuid FROM members ORDER BY id")]
        for i in range(240):
            age=rng.randrange(0,89)
            t=now-age*86400-rng.randrange(0,86400)
            q=rng.choices([420,440,450,430,0],[28,22,25,15,10])[0]
            mid=f"DEMO_{i}"
            c.execute("INSERT INTO matches(match_id,queue_id,played_at,duration_sec) VALUES(?,?,?,?)",(mid,q,t,2000))
            # Most share matches, some are low activity or inactive
            pool=members[:7]+(members[7:9] if i%4==0 else [])+(members[9:10] if i%13==0 else [])
            chosen=rng.sample(pool,k=min(len(pool),rng.randint(1,5)))
            for j,p in enumerate(chosen):
                win=rng.choice([0,1])
                team_id=100 if q==0 and j<len(chosen)//2 else (200 if q==0 else 100)
                c.execute("INSERT INTO match_players VALUES(?,?,?,?,?,?,?)",(mid,p["puuid"],team_id,win,rng.randrange(1,12),rng.randrange(0,10),rng.randrange(2,17)))
        c.execute("UPDATE sync_status SET last_started=?,last_finished=?,running=0,imported_matches=? WHERE id=1",(now-300,now-300,240))
