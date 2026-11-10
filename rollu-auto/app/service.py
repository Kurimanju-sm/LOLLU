"""Opt-in LoL match collection + monthly club activity (NOT skill MMR)."""
import os
import time
import calendar
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from .db import session
from .riot import RiotError

KST = timezone(timedelta(hours=9))
QUEUE_LABELS = {0: "내전/사용자 설정", 420: "솔로·듀오", 440: "자유랭크", 450: "칼바람", 400: "일반 교차", 430: "일반 비공개", 480: "빠른 대전", 490: "빠른 대전", 700: "격전"}


def category(queue_id):
    q = int(queue_id)
    if q == 0: return "custom"
    if q == 420: return "solo_duo"
    if q == 440: return "flex"
    if q == 450: return "aram"
    if q in (400, 430, 480, 490): return "normal"
    return "other"


def current_month():
    return datetime.now(KST).strftime('%Y-%m')


def add_month(month, delta):
    yyyy, mm = map(int, month.split('-'))
    index = yyyy * 12 + (mm - 1) + delta
    return f'{index//12:04d}-{index%12+1:02d}'


def month_bounds(month):
    """Korean local monthly boundary converted to UTC epoch seconds."""
    import re
    if not re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])', month):
        raise ValueError('YYYY-MM 형식의 월을 입력하세요.')
    year, mm = map(int, month.split('-'))
    begin = datetime(year, mm, 1, tzinfo=KST)
    following = datetime(year + (mm == 12), (mm % 12) + 1, 1, tzinfo=KST)
    return int(begin.timestamp()), int(following.timestamp())


def ingest_match(c, payload):
    """Persist only approved active members, and require separate custom-game consent."""
    info = payload.get('info') or {}
    meta = payload.get('metadata') or {}
    match_id = meta.get('matchId')
    players = info.get('participants') or []
    if not match_id or not players: return False
    queue_id = int(info.get('queueId') or 0)
    millis = info.get('gameStartTimestamp') or info.get('gameCreation') or 0
    played_at = int(millis / 1000)
    if played_at <= 0: return False
    approved = {r['puuid']: r for r in c.execute('SELECT puuid,consent_custom FROM members WHERE approved=1 AND active=1 AND consent_public=1')}
    allowed = [p for p in players if p.get('puuid') in approved and (queue_id != 0 or approved[p['puuid']]['consent_custom'])]
    if not allowed: return False
    inserted = c.execute('INSERT OR IGNORE INTO matches(match_id,queue_id,played_at,duration_sec) VALUES(?,?,?,?)', (match_id,queue_id,played_at,int(info.get('gameDuration') or 0))).rowcount
    for p in allowed:
        c.execute('''INSERT OR REPLACE INTO match_players(match_id,puuid,team_id,win,kills,deaths,assists)
            VALUES(?,?,?,?,?,?,?)''',(match_id,p['puuid'],int(p.get('teamId') or 0),int(bool(p.get('win'))),int(p.get('kills') or 0),int(p.get('deaths') or 0),int(p.get('assists') or 0)))
    return bool(inserted)


async def sync_all(riot, force=False):
    """Sequential, rate-limited fetch. A failed request is never an inactivity signal."""
    if not riot.api_key: raise RiotError('RIOT_API_KEY가 없어 자동 수집을 실행할 수 없습니다.')
    started = int(time.time())
    with session() as c:
        running = c.execute('SELECT running,last_started FROM sync_status WHERE id=1').fetchone()
        if running['running'] and started - (running['last_started'] or 0) < 7200:
            return {'skipped':'이미 동기화가 진행 중입니다.'}
        c.execute('UPDATE sync_status SET running=1,last_started=?,last_error=NULL WHERE id=1',(started,))
    imported, failures = 0, []
    try:
        with session() as c:
            members = [dict(r) for r in c.execute('SELECT * FROM members WHERE approved=1 AND active=1 AND consent_public=1 ORDER BY id')]
        lookback = max(7, min(365, int(os.getenv('SYNC_LOOKBACK_DAYS','180'))))
        max_games = max(100, min(1000, int(os.getenv('SYNC_MAX_MATCHES_PER_MEMBER','400'))))
        for member in members:
            try:
                now = int(time.time())
                start = max(now-lookback*86400, (member['last_sync_at'] or 0)-2*86400)
                match_ids, offset, truncated = [], 0, False
                while offset < max_games:
                    count = min(100, max_games-offset)
                    batch = await riot.match_ids(member['puuid'],start,start=offset,count=count)
                    match_ids.extend(batch)
                    if len(batch)<count: break
                    offset+=len(batch)
                    if offset>=max_games: truncated=True
                for mid in dict.fromkeys(match_ids):
                    with session() as c:
                        present = c.execute('SELECT 1 FROM match_players WHERE match_id=? AND puuid=?',(mid,member['puuid'])).fetchone()
                    if present: continue
                    try:
                        payload = await riot.match(mid)
                        with session() as c:
                            if ingest_match(c,payload): imported+=1
                    except RiotError as exc:
                        if '찾을 수 없습니다' in str(exc): continue
                        raise
                if truncated: raise RiotError(f'최근 {max_games}판 조회 제한에 도달했습니다. 수집 범위를 조정하세요.')
                with session() as c:
                    c.execute('UPDATE members SET last_sync_at=?,first_sync_at=COALESCE(first_sync_at,?),last_sync_error=NULL WHERE id=?',(now,now,member['id']))
            except Exception as exc:
                msg=str(exc)[:180]
                failures.append(f'{member["nickname"]}: {msg}')
                with session() as c:
                    c.execute('UPDATE members SET last_sync_error=? WHERE id=?',(msg,member['id']))
        with session() as c:
            # Keep at least the configured number of full historic months, for admin review.
            months = max(3, min(60,int(os.getenv('HISTORY_MONTHS','18'))))
            oldest_month = add_month(current_month(), -months)
            cutoff,_ = month_bounds(oldest_month)
            c.execute('DELETE FROM matches WHERE played_at < ?',(cutoff,))
            c.execute('UPDATE sync_status SET last_finished=?,last_error=?,imported_matches=imported_matches+? WHERE id=1',
                      (int(time.time()),' / '.join(failures[:4]) if failures else None,imported))
        return {'imported':imported,'member_failures':len(failures),'errors':failures[:4]}
    except Exception as exc:
        with session() as c: c.execute('UPDATE sync_status SET last_error=? WHERE id=1',(str(exc)[:200],))
        raise
    finally:
        with session() as c: c.execute('UPDATE sync_status SET running=0 WHERE id=1')


def dashboard(days=30, mode='shared', month=None, include_left=False):
    """Calendar-month query for UI, rolling days available for backwards-compatible API/tests.

    A new month starts at 00:00 Asia/Seoul; old match rows remain available to admins.
    """
    if month:
        since, until = month_bounds(month)
        days = max(1, (min(int(time.time()),until)-since)//86400 + 1)
    else:
        days = min(90,max(7,int(days)))
        since, until = int(time.time())-days*86400, int(time.time())+1
    if until > int(time.time())+1: until=int(time.time())+1
    with session() as c:
        where = '''approved=1 AND consent_public=1 AND joined_at<? AND (left_at IS NULL OR left_at>=?)''' if include_left else '''approved=1 AND active=1 AND consent_public=1'''
        params = (until,since) if include_left else ()
        members = [dict(r) for r in c.execute(f'''SELECT id,nickname,game_name,tag_line,puuid,joined_at,active,left_at,consent_custom,first_sync_at,last_sync_at,last_sync_error FROM members WHERE {where}''',params)]
        eligible = {m['puuid'] for m in members}
        rows = [dict(r) for r in c.execute('''SELECT m.match_id,m.queue_id,m.played_at,p.puuid,p.team_id,p.win
            FROM matches m JOIN match_players p ON p.match_id=m.match_id
            JOIN members u ON u.puuid=p.puuid AND u.approved=1 AND u.consent_public=1
            WHERE m.played_at>=? AND m.played_at<? AND (m.queue_id<>0 OR u.consent_custom=1)
            ORDER BY m.played_at DESC''',(since,until))]
        status = dict(c.execute('SELECT * FROM sync_status WHERE id=1').fetchone())
    by_match=defaultdict(list)
    for row in rows:
        if row['puuid'] in eligible: by_match[row['match_id']].append(row)
    stat={m['puuid']:{'total':0,'wins':0,'shared':0,'custom':0,'duo_observed':0,'last_played_at':None,'last_shared_at':None,'by_mode':Counter(),'shared_by_mode':Counter(),'partners':Counter()} for m in members}
    for matched in by_match.values():
        for row in matched:
            item=stat[row['puuid']]
            cat=category(row['queue_id'])
            item['total']+=1
            item['wins']+=int(row['win'])
            item['by_mode'][cat]+=1
            item['last_played_at']=max(item['last_played_at'] or 0,row['played_at'])
            others=[p for p in matched if p['puuid']!=row['puuid'] and (cat=='custom' or (p['team_id'] is not None and p['team_id']==row['team_id']))]
            if others:
                item['shared']+=1
                item['shared_by_mode'][cat]+=1
                item['last_shared_at']=max(item['last_shared_at'] or 0,row['played_at'])
                for p in others: item['partners'][p['puuid']]+=1
                if cat=='solo_duo': item['duo_observed']+=1
            if cat=='custom': item['custom']+=1
    by_puuid={m['puuid']:m['nickname'] for m in members}
    results=[]
    threshold=max(2,int(os.getenv('ACTIVE_SHARED_GAMES_30D','5')))
    # In month mode, a stable threshold allows month-to-month comparison.
    if not month: threshold=max(2,round(threshold*days/30))
    for m in members:
        s=stat[m['puuid']]
        if m['last_sync_error'] or not m['last_sync_at']: health='sync_issue'
        elif s['shared']>=threshold: health='active'
        elif s['shared']>0: health='light'
        elif s['total']>0: health='solo_only'
        else: health='no_matches'
        partners=[{'nickname':by_puuid[puuid],'games':n} for puuid,n in s['partners'].most_common() if puuid in by_puuid]
        results.append({'id':m['id'],'nickname':m['nickname'],'riot_id':f'{m["game_name"]}#{m["tag_line"]}',
            'total':s['total'],'wins':s['wins'],'shared':s['shared'],'custom':s['custom'],'duo_observed':s['duo_observed'],
            'win_rate':round(s['wins']*100/s['total']) if s['total'] else None,'last_played_at':s['last_played_at'],
            'last_shared_at':s['last_shared_at'],'by_mode':dict(s['by_mode']),'shared_by_mode':dict(s['shared_by_mode']),
            'partners':partners,'status':health,'last_sync_at':m['last_sync_at'],'sync_error':bool(m['last_sync_error']),
            'is_left':not bool(m['active']),'left_at':m['left_at']})
    def score(member):
        if mode=='total': return member['total']
        if mode=='custom': return member['custom']
        if mode in ('solo_duo','flex','aram','normal'): return member['by_mode'].get(mode,0)
        if mode in ('shared_solo_duo','shared_flex','shared_aram','shared_normal'):
            return member['shared_by_mode'].get(mode.replace('shared_',''),0)
        return member['shared']
    results.sort(key=lambda x:(-score(x),-x['total'],x['nickname']))
    summary={'members':len(results),'active':sum(x['status']=='active' for x in results),
             'light':sum(x['status']=='light' for x in results),
             'no_club':sum(x['status'] in ('solo_only','no_matches') for x in results),
             'sync_issue':sum(x['status']=='sync_issue' for x in results)}
    return {'days':days,'month':month,'mode':mode,'members':results,'summary':summary,
            'sync':{'last_finished':status['last_finished'],'running':bool(status['running']),'error':bool(status['last_error'])},
            'rule': f'{month or "최근 기간"} 같은 팀·경기 {threshold}회 이상: 활발 / 1~{threshold-1}회: 가끔 참여. 함께 큐를 돌렸다고 확정하는 지표는 아닙니다.'}


def historic_months():
    months=max(3,min(60,int(os.getenv('HISTORY_MONTHS','18'))))
    now=current_month()
    return [add_month(now,-x) for x in range(months+1)]
