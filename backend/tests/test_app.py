import os
os.environ["DEMO_MODE"] = "1"
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.db import session
from app.main import app
from app.service import category, dashboard, ingest_match

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('DEMO_MODE','1')
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'rollu_test.db'))
    monkeypatch.setenv('ADMIN_PASSWORD','strong-password-for-testing')
    monkeypatch.setenv('JOIN_CODE','private-join-code')
    with TestClient(app) as test:
        yield test

def test_public_dashboard_populated(client):
    r=client.get('/api/dashboard?days=30&mode=shared')
    assert r.status_code==200
    d=r.json()
    assert d['summary']['members']==12
    assert d['members'][0]['shared']>=d['members'][1]['shared']
    assert set(d['summary'])=={'members','active','light','no_club','sync_issue'}

def test_mode_and_classification(client):
    assert category(0)=='custom'
    assert category(420)=='solo_duo'
    assert category(440)=='flex'
    assert category(450)=='aram'
    assert client.get('/api/dashboard?days=90&mode=aram').status_code==200

def test_join_approve_delete(client):
    payload={"nickname":"새회원","game_name":"아무개","tag_line":"KR1","join_code":"demo","consent_public":True,"consent_custom":True}
    r=client.post('/api/join',json=payload)
    assert r.status_code==201, r.text
    token=r.json()['management_token']
    r=client.post('/api/join',json={**payload,'consent_public':False})
    assert r.status_code==422
    assert client.get('/api/admin/members').status_code==401
    assert client.post('/api/admin/login',json={'password':'strong-password-for-testing'}).status_code==200
    data=client.get('/api/admin/members').json()['members']
    pending=next(x for x in data if x['nickname']=='새회원')
    assert not pending['approved']
    r=client.post(f'/api/admin/members/{pending["id"]}/approve')
    assert r.status_code==200
    assert client.get('/api/dashboard').json()['summary']['members']==13
    assert client.post('/api/me/consent',json={'token':token,'consent_custom':False}).status_code==200
    assert client.post('/api/me/delete',json={'token':token}).status_code==200
    assert client.get('/api/dashboard').json()['summary']['members']==12
    assert client.post('/api/me/delete',json={'token':token}).status_code==401

def test_failed_sync_not_marked_as_ghost(client):
    with session() as c:
        c.execute("UPDATE members SET last_sync_error='API unavailable' WHERE id=1")
    r=client.get('/api/dashboard?days=30').json()
    m=next(m for m in r['members'] if m['id']==1)
    assert m['status']=='sync_issue'

def test_custom_optin_restriction(client):
    with session() as c:
        approved=c.execute("SELECT puuid FROM members WHERE id=1").fetchone()['puuid']
        c.execute('UPDATE members SET consent_custom=0 WHERE id=1')
        r=ingest_match(c,{
          'metadata':{'matchId':'CUSTOM_NEW_1'},
          'info':{'queueId':0,'gameStartTimestamp':int(time.time()*1000),'participants':[{'puuid':approved,'teamId':100,'win':True}]}
        })
        assert not r
        c.execute('UPDATE members SET consent_custom=1 WHERE id=1')
        r=ingest_match(c,{
          'metadata':{'matchId':'CUSTOM_NEW_1'},
          'info':{'queueId':0,'gameStartTimestamp':int(time.time()*1000),'participants':[{'puuid':approved,'teamId':100,'win':True}]}
        })
        assert r

def test_live_mode_requires_club_view_code(tmp_path, monkeypatch):
    from app import main as main_module
    monkeypatch.setattr(main_module,'DEMO',False)
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'live_mode.db'))
    monkeypatch.setenv('VIEW_CODE','only-rollu-members')
    monkeypatch.setenv('JOIN_CODE','private-join-code')
    monkeypatch.setenv('ADMIN_PASSWORD','strong-password-for-testing')
    with TestClient(app) as test:
        assert test.get('/api/dashboard').status_code==401
        assert test.post('/api/viewer/login',json={'code':'wrong'}).status_code==401
        assert test.post('/api/viewer/login',json={'code':'only-rollu-members'}).status_code==200
        assert test.get('/api/dashboard').status_code==200
        assert test.get('/api/dashboard').json()['summary']['members']==0
    monkeypatch.setattr(main_module,'DEMO',True)
