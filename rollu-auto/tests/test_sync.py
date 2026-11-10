import os
os.environ['DEMO_MODE'] = '1'
import time
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import session
from app.service import sync_all, dashboard

class FakeRiot:
    api_key='test-fake-key'
    async def match_ids(self, puuid, since, start=0, count=100):
        return ['KR_FAKE_001'] if start==0 else []
    async def match(self, match_id):
        with session() as c:
            pus=[row['puuid'] for row in c.execute('SELECT puuid FROM members WHERE approved=1 ORDER BY id LIMIT 2')]
        return {'metadata':{'matchId':match_id},'info':{'queueId':440,'gameStartTimestamp':int(time.time()*1000),'gameDuration':1800,'participants':[{'puuid':pus[0],'teamId':100,'win':True},{'puuid':pus[1],'teamId':100,'win':True}]}}

@pytest.mark.asyncio
async def test_mock_sync(tmp_path, monkeypatch):
    # API client mocked, no Riot servers touched.
    monkeypatch.setenv('DATABASE_PATH',str(tmp_path/'sync.db'))
    with TestClient(app):
        result=await sync_all(FakeRiot())
        assert result['imported']==1
        assert result['member_failures']==0
        with session() as c:
            assert c.execute("SELECT COUNT(*) FROM match_players WHERE match_id='KR_FAKE_001'").fetchone()[0]==2
        d=dashboard(30,'shared')
        a,b=d['members'][:2]
        assert sum(m['shared']>=1 for m in d['members'])>=2
