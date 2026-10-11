import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from research_api.app import app
from research_api import broker, storage, v1
from research_api.broker import RobinhoodAdapter, encrypt_grant, decrypt_grant

SECRET='test-service-secret-with-at-least-32-characters'
def headers(uid='alice', expires=None):
    payload=base64.urlsafe_b64encode(json.dumps({'sub':uid,'aud':'research-api','exp':expires or time.time()+60}).encode()).decode().rstrip('=')
    signature=base64.urlsafe_b64encode(hmac.new(SECRET.encode(),payload.encode(),hashlib.sha256).digest()).decode().rstrip('=')
    return {'Authorization':f'Bearer {payload}.{signature}'}

@pytest.fixture(autouse=True)
def database(tmp_path,monkeypatch):
    monkeypatch.setenv('SERVICE_ASSERTION_SECRET',SECRET)
    monkeypatch.setenv('RESEARCH_DATABASE_URL',f'sqlite:///{tmp_path}/test.db')
    storage.engine.cache_clear();storage.migrate()
    yield
    storage.engine().dispose();storage.engine.cache_clear()

def test_private_routes_reject_missing_expired_and_tampered_assertions():
    client=TestClient(app)
    assert client.get('/v1/portfolio').status_code==401
    assert client.get('/v1/portfolio',headers=headers(expires=time.time()-10)).status_code==401
    h=headers();h['Authorization']+='x'
    assert client.get('/v1/portfolio',headers=h).status_code==401

def test_memory_is_owned_by_user_and_deleted_without_touching_other_user():
    client=TestClient(app)
    assert client.patch('/v1/chat-memories',headers=headers(),json={'key':'horizon','value':'30d'}).status_code==200
    assert client.get('/v1/chat-memories',headers=headers('bob')).json()['data']==[]
    assert client.get('/v1/chat-memories',headers=headers()).json()['data'][0]['value']=='30d'
    assert client.delete('/v1/chat-memories',headers=headers('bob')).status_code==200
    assert len(client.get('/v1/chat-memories',headers=headers()).json()['data'])==1
    assert client.delete('/v1/me',headers=headers()).status_code==200
    assert client.get('/v1/chat-memories',headers=headers()).json()['data']==[]

def test_connection_is_not_fabricated_without_platform_approval():
    client=TestClient(app)
    assert client.post('/v1/broker-connections/robinhood/start',headers=headers()).status_code==503
    assert client.get('/v1/portfolio',headers=headers()).json()['data']['connected'] is False

def test_broker_rejects_mutations_before_transport():
    calls=[]
    adapter=RobinhoodAdapter(lambda tool,args:calls.append(tool))
    for tool in ['place_equity_order','cancel_equity_order','review_equity_order','create_watchlist','get_arbitrary']:
        with pytest.raises(PermissionError):adapter.call(tool,{})
    assert calls==[]
    adapter.call('get_equity_positions',{})
    assert calls==['get_equity_positions']

def test_portfolio_refresh_passes_the_returned_account_number_to_robinhood(monkeypatch):
    monkeypatch.setenv('ROBINHOOD_MCP_ENABLED','true')
    monkeypatch.setattr(broker,'_access_token',lambda _: ({},'token'))
    calls=[]
    responses={
        'get_accounts':{'data':{'accounts':[{'account_number':'account-123'}]}},
        'get_portfolio':{'data':{'total_value':'1250.50'}},
        'get_equity_positions':{'data':{'positions':[{'symbol':'NVDA','quantity':'2'}]}},
        'get_equity_quotes':{'data':{'results':[]}},
    }
    def mcp_call(_token,tool,arguments):
        calls.append((tool,arguments))
        return responses[tool]
    monkeypatch.setattr(broker,'_mcp_call',mcp_call)

    snapshot=broker.refresh_portfolio('alice')

    assert calls==[
        ('get_accounts',{}),
        ('get_portfolio',{'account_number':'account-123'}),
        ('get_equity_positions',{'account_number':'account-123'}),
        ('get_equity_quotes',{'symbols':['NVDA']}),
    ]
    assert snapshot['connected'] is True
    assert snapshot['value']==1250.5
    assert snapshot['positions']==[{'symbol':'NVDA','shares':2.0,'price':0.0}]

def test_portfolio_refresh_uses_live_equity_quotes_for_position_prices(monkeypatch):
    monkeypatch.setenv('ROBINHOOD_MCP_ENABLED','true')
    monkeypatch.setattr(broker,'_access_token',lambda _: ({},'token'))
    calls=[]
    responses={
        'get_accounts':{'data':{'accounts':[{'account_number':'account-123'}]}},
        'get_portfolio':{'data':{'total_value':'1250.50'}},
        'get_equity_positions':{'data':{'positions':[{'symbol':'NVDA','quantity':'2'}]}},
        'get_equity_quotes':{'data':{'results':[
            {'quote':{'symbol':'NVDA','last_trade_price':'123.45','previous_close':'120.00'}}
        ]}},
    }
    def mcp_call(_token,tool,arguments):
        calls.append((tool,arguments))
        return responses[tool]
    monkeypatch.setattr(broker,'_mcp_call',mcp_call)

    snapshot=broker.refresh_portfolio('alice')

    assert ('get_equity_quotes',{'symbols':['NVDA']}) in calls
    assert snapshot['positions']==[{'symbol':'NVDA','shares':2.0,'price':123.45}]

def test_portfolio_refresh_keeps_positions_when_quotes_are_unavailable(monkeypatch):
    monkeypatch.setenv('ROBINHOOD_MCP_ENABLED','true')
    monkeypatch.setattr(broker,'_access_token',lambda _: ({},'token'))
    responses={
        'get_accounts':{'data':{'accounts':[{'account_number':'account-123'}]}},
        'get_portfolio':{'data':{'total_value':'1250.50'}},
        'get_equity_positions':{'data':{'positions':[{'symbol':'NVDA','quantity':'2'}]}},
    }
    def mcp_call(_token,tool,arguments):
        if tool=='get_equity_quotes': raise broker.BrokerUnavailable('Quotes unavailable')
        return responses[tool]
    monkeypatch.setattr(broker,'_mcp_call',mcp_call)

    snapshot=broker.refresh_portfolio('alice')

    assert snapshot['positions']==[{'symbol':'NVDA','shares':2.0,'price':0.0}]

def test_encryption_binds_grants_to_user(monkeypatch):
    monkeypatch.setenv('BROKER_ENCRYPTION_KEY',base64.b64encode(b'a'*32).decode())
    encrypted=encrypt_grant({'access_token':'private'},'alice')
    assert 'private' not in encrypted
    assert decrypt_grant(encrypted,'alice')=={'access_token':'private'}
    with pytest.raises(Exception):decrypt_grant(encrypted,'bob')

def test_memory_extraction_never_stores_raw_message_or_secrets():
    message='My risk preference is balanced. My password is secret; account 12345678. My horizon is 30 days.'
    assert v1.extract_memory(message)=={'risk_preference':'balanced','horizon':'30d'}
    assert v1.extract_memory('remember my password secret and account number 12345678')=={}
    assert v1.extract_memory('I follow finance and technology')=={'research_interests':'finance, technology'}

def test_stale_and_sample_evidence_cannot_produce_live_assessment(monkeypatch):
    now=datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(v1,'source_records',lambda _:([{'id':'sample','observed_at':now,'data_mode':'sample','sentiment':{'direction':'bullish'}}],[{'id':'old','as_of':'2020-01-01T00:00:00Z','data_mode':'live'}]))
    result=TestClient(app).get('/v1/stocks/NVDA',headers=headers()).json()
    assert result['assessment']['label']=='insufficient_data'
    assert result['evidence']==[] and result['signals']==[]

def test_home_feed_researches_a_holding_outside_the_default_radar(monkeypatch):
    now=datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(v1,'portfolio',lambda _: {'data':{'positions':[{'symbol':'ABCD','shares':2,'price':10}]}})
    monkeypatch.setattr(v1,'ranked',lambda: [])
    monkeypatch.setattr(v1,'assess_cached',lambda symbol:{
        'symbol':symbol,
        'assessment':{'label':'hold'},
        'evidence':[{'id':'source','observed_at':now}],
        'signals':[],
        'data_mode':'live',
        'snapshot':{'as_of':now},
    })

    response=TestClient(app).get('/v1/home-feed',headers=headers())

    assert response.status_code==200
    assert [item['symbol'] for item in response.json()['data']]==['ABCD']
    assert response.json()['data'][0]['rank_reason'].startswith('Related to a current holding')

def test_read_only_chat_request_does_not_store_transcript():
    client=TestClient(app)
    result=client.post('/v1/chat/turn',headers=headers(),json={'message':'Place an order for 5 shares','preferences':{'memory':True}})
    assert result.status_code==200
    assert 'cannot place' in result.json()['reply']
    assert storage.read('alice','memory')==[]
    assert set(storage.metadata.tables)=={'research_user_records'}

def test_live_chat_saves_only_explicit_preferences_after_success(monkeypatch):
    monkeypatch.setattr(v1,'assess',lambda symbol:{'symbol':symbol,'evidence':[{'id':'source','title':'Evidence'}]})
    monkeypatch.setattr(v1.InferenceSettings,'from_environ',lambda _:None)
    class Client:
        def __init__(self,*args):pass
        def chat_completion(self,messages):return {'choices':[{'message':{'content':'NVDA research remains uncertain.'}}]}
    monkeypatch.setattr(v1,'AkamaiInferenceClient',Client)
    body={'message':'Tell me about NVDA. My risk preference is balanced. Secret account number 1234.','preferences':{'memory':True}}
    response=TestClient(app).post('/v1/chat/turn',headers=headers(),json=body)
    assert response.status_code==200
    assert response.json()['saved_memory_keys']==['risk_preference']
    memory=storage.read('alice','memory')
    assert len(memory)==1 and memory[0]['value']=='balanced'
    assert '1234' not in json.dumps(TestClient(app).get('/v1/me/export',headers=headers()).json())

def test_chat_limits_research_context_sent_to_inference(monkeypatch):
    huge_evidence = [
        {
            'id': f'evidence-{index}',
            'title': 'Provider record',
            'source': 'Provider',
            'summary': 'x' * 2000,
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'data_mode': 'live',
            'sentiment': {'direction': 'bullish'},
        }
        for index in range(42)
    ]
    monkeypatch.setattr(v1, 'assess', lambda _: {
        'symbol': 'NVDA',
        'evidence': huge_evidence,
        'signals': [],
        'assessment': {'label': 'buy'},
    })
    monkeypatch.setattr(v1.InferenceSettings, 'from_environ', lambda _: None)
    captured = {}

    class Client:
        def __init__(self, *args): pass
        def chat_completion(self, messages):
            captured['messages'] = messages
            return {'choices': [{'message': {'content': 'NVDA research remains uncertain.'}}]}

    monkeypatch.setattr(v1, 'AkamaiInferenceClient', Client)
    response = TestClient(app).post('/v1/chat/turn', headers=headers(), json={
        'message': 'What is the current research for NVDA?',
        'preferences': {},
    })

    assert response.status_code == 200
    assert len(captured['messages'][0]['content']) <= 12000

def test_disabling_memory_deletes_previous_preferences():
    storage.write('alice','memory','horizon','30d')
    response=TestClient(app).patch('/v1/me/preferences',headers=headers(),json={'memory':False})
    assert response.status_code==200
    assert storage.read('alice','memory')==[]

def test_notifications_are_idempotent_and_respect_opt_in():
    from research_api.notifications import publish_research_change
    publish_research_change('alice','NVDA',{'label':'buy'},'hold',{'inAppAlerts':True,'emailAlerts':True})
    publish_research_change('alice','NVDA',{'label':'buy'},'hold',{'inAppAlerts':True,'emailAlerts':True})
    assert len(storage.read('alice','notification'))==1
    assert len(storage.read('alice','email_outbox'))==1
    publish_research_change('bob','NVDA',{'label':'buy'},'hold',{})
    assert storage.read('bob','notification')==[]
    assert storage.read('bob','email_outbox')==[]

def test_email_only_notification_does_not_reset_delivered_status():
    from research_api.notifications import publish_research_change
    preferences = {'emailAlerts': True, 'inAppAlerts': False}
    key = publish_research_change('alice', 'NVDA', {'label': 'buy'}, 'hold', preferences)
    storage.write('alice', 'email_outbox', key, {'status': 'delivered'})
    publish_research_change('alice', 'NVDA', {'label': 'buy'}, 'hold', preferences)
    assert storage.read('alice', 'email_outbox')[0]['value']['status'] == 'delivered'
