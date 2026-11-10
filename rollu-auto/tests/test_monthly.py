import os
os.environ['DEMO_MODE']='1'
import calendar
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.db import session
from app.service import KST, dashboard, current_month, add_month, month_bounds, historic_months, ingest_match


def test_kst_boundaries_and_month_rollover():
    # Nov 1st 00:00 KST is Oct 31st 15:00 UTC.
    start, end = month_bounds('2026-11')
    assert datetime.fromtimestamp(start, KST).isoformat() == '2026-11-01T00:00:00+09:00'
    assert end-start==30*86400
    assert add_month('2026-12',1)=='2027-01'
    assert add_month('2027-01',-1)=='2026-12'


def test_shared_rank_and_private_monthly_archive(tmp_path,monkeypatch):
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'months.db'))
    monkeypatch.setenv('ADMIN_PASSWORD','strong-test-password')
    monkeypatch.setenv('JOIN_CODE','private-join-code')
    with TestClient(app) as client:
        now_month=current_month()
        last_month=add_month(now_month,-1)
        older, _ = month_bounds(last_month)
        today, _ = month_bounds(now_month)
        with session() as c:
            # Synthetic members already preloaded in demo, set joined date before prior month.
            c.execute('UPDATE members SET joined_at=?,first_sync_at=?,last_sync_at=?',(older-86400,older-86400,today+1))
            pus=[x['puuid'] for x in c.execute('SELECT puuid FROM members ORDER BY id LIMIT 3')]
            for mid,when,queue,team2 in [('PREV_SOLO',older+43200,420,100),('PREV_FLEX',older+86400,440,200),('THIS_FLEX',today+1800,440,100)]:
                ingest_match(c, {'metadata':{'matchId':mid},'info':{'queueId':queue,'gameStartTimestamp':when*1000,'participants':[
                    {'puuid':pus[0],'teamId':100,'win':True},
                    {'puuid':pus[1],'teamId':team2,'win':True},
                    {'puuid':pus[2],'teamId':200,'win':False},
                ]}})
        prev=dashboard(mode='shared_solo_duo',month=last_month,include_left=True)
        one=next(x for x in prev['members'] if x['riot_id']=='파랑별#KR1')
        assert one['shared_by_mode']['solo_duo']>=1
        assert prev['mode']=='shared_solo_duo'
        assert any(x['nickname']=='초코구름' for x in one['partners'])
        # Monthly view excludes older-only synthetic rows from the new period.
        curr=dashboard(mode='shared_flex',month=now_month)
        this_one=next(x for x in curr['members'] if x['nickname']=='파랑별')
        assert this_one['shared_by_mode'].get('flex',0)>=1
        assert client.get('/api/admin/months').status_code==401
        assert client.get(f'/api/admin/dashboard?month={last_month}').status_code==401
        client.post('/api/admin/login',json={'password':'strong-test-password'})
        months=client.get('/api/admin/months').json()['months']
        assert last_month in months
        assert client.get(f'/api/admin/dashboard?month={last_month}').status_code==200
        # 
        # Offboard a member without erasing the previous month.
        members = client.get('/api/admin/members').json()['members']
        member = next(x for x in members if x['nickname']=='파랑별')
        response = client.post(f'/api/admin/members/{member["id"]}/leave')
        assert response.status_code == 200, response.text
        assert not any(x['id']==member['id'] for x in client.get('/api/dashboard').json()['members'])
        previous = client.get(f'/api/admin/dashboard?month={last_month}').json()['members']
        offboarded = next(x for x in previous if x['id']==member['id'])
        assert offboarded['is_left'] is True
        assert offboarded['shared_by_mode'].get('solo_duo',0)>=1
        # On data erasure, all identifiable history disappears as well.
        response=client.delete(f'/api/admin/members/{member["id"]}')
        assert response.status_code == 200
        assert not any(x['id']==member['id'] for x in client.get(f'/api/admin/dashboard?month={last_month}').json()['members'])
