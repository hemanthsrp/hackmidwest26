"""Read-only broker capability boundary; never hand this transport to an LLM."""
from collections.abc import Callable
import base64
import hashlib
import secrets
import os
import json
import re
import time
from urllib.parse import urlencode, urlparse
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import httpx

from . import storage

ALLOWED_TOOLS = frozenset({'get_accounts', 'get_portfolio', 'get_equity_positions', 'get_equity_quotes'})
MCP_URL = 'https://agent.robinhood.com/mcp/trading'
OAUTH_METADATA_URL = 'https://agent.robinhood.com/.well-known/oauth-authorization-server'
TOKEN_URL = 'https://api.robinhood.com/oauth2/token/'
REGISTRATION_URL = 'https://agent.robinhood.com/oauth/trading/register'
CLIENT_RECORD_USER = '__folio_application__'
CLIENT_RECORD_KEY = 'robinhood_trading_mcp'

class BrokerUnavailable(RuntimeError):
    """A safe provider failure that contains no credential or response data."""

class RobinhoodAdapter:
    def __init__(self, transport: Callable): self._transport = transport
    def call(self, tool: str, arguments: dict):
        if tool not in ALLOWED_TOOLS:
            raise PermissionError('Broker capability is not permitted')
        return self._transport(tool, arguments)

def encrypt_grant(grant: dict, user_id: str) -> str:
    key = base64.b64decode(os.environ['BROKER_ENCRYPTION_KEY'], validate=True)
    if len(key) != 32: raise ValueError('A 32-byte encryption key is required')
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, json.dumps(grant).encode(), user_id.encode())
    return 'v1.' + base64.urlsafe_b64encode(nonce + ciphertext).decode()

def decrypt_grant(value: str, user_id: str) -> dict:
    version, encoded = value.split('.', 1)
    if version != 'v1': raise ValueError('Unsupported encryption key version')
    key = base64.b64decode(os.environ['BROKER_ENCRYPTION_KEY'], validate=True)
    raw = base64.urlsafe_b64decode(encoded)
    return json.loads(AESGCM(key).decrypt(raw[:12], raw[12:], user_id.encode()))

def _enabled() -> bool:
    return os.getenv('ROBINHOOD_MCP_ENABLED', 'false').lower() == 'true'

def _redirect_uri() -> str:
    configured = os.getenv('ROBINHOOD_REDIRECT_URI')
    if configured:
        return configured
    origin = os.getenv('AUTH_URL', 'http://localhost:3100').rstrip('/')
    return origin + '/api/broker/robinhood/callback'

def _client_registration(redirect_uri: str) -> dict:
    rows = storage.read(CLIENT_RECORD_USER, 'broker_clients')
    for row in rows:
        if row['key'] == CLIENT_RECORD_KEY and row['value'].get('redirect_uri') == redirect_uri:
            return row['value']
    # This is a public OAuth client. It has no client secret; PKCE protects each
    # user's authorization code. Register only the one configured callback.
    try:
        response = httpx.post(REGISTRATION_URL, json={
            'client_name': 'Folio local research app',
            'redirect_uris': [redirect_uri],
            'grant_types': ['authorization_code', 'refresh_token'],
            'response_types': ['code'],
            'token_endpoint_auth_method': 'none',
            'scope': 'internal',
        }, timeout=12)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data.get('client_id'), str) or redirect_uri not in data.get('redirect_uris', []):
            raise ValueError('Invalid client registration')
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise BrokerUnavailable('Robinhood did not accept this application registration. No account was connected.') from None
    registration = {'client_id': data['client_id'], 'redirect_uri': redirect_uri}
    storage.write(CLIENT_RECORD_USER, 'broker_clients', CLIENT_RECORD_KEY, registration)
    return registration

def begin_authorization(user_id: str) -> str:
    if not _enabled():
        raise BrokerUnavailable('Robinhood linking is disabled for this deployment.')
    try:
        key = base64.b64decode(os.environ['BROKER_ENCRYPTION_KEY'], validate=True)
        if len(key) != 32: raise ValueError()
    except (KeyError, ValueError):
        raise BrokerUnavailable('Robinhood token encryption is not configured.') from None
    redirect_uri = _redirect_uri()
    for row in storage.read(user_id, 'broker_oauth_pending'):
        try:
            old_pending = decrypt_grant(row['value']['grant'], user_id)
        except (KeyError, ValueError):
            old_pending = {}
        if old_pending.get('expires_at', 0) < time.time():
            storage.remove(user_id, 'broker_oauth_pending', row['key'])
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.path != '/api/broker/robinhood/callback' or parsed.query or parsed.fragment:
        raise BrokerUnavailable('Robinhood callback URL is not configured correctly.')
    try:
        registration = _client_registration(redirect_uri)
    except RuntimeError:
        raise
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(32)
    pending = {'client_id': registration['client_id'], 'redirect_uri': redirect_uri, 'code_verifier': verifier, 'expires_at': int(time.time()) + 600}
    storage.write(user_id, 'broker_oauth_pending', hashlib.sha256(state.encode()).hexdigest(), {'grant': encrypt_grant(pending, user_id)})
    query = urlencode({
        'client_id': registration['client_id'],
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'internal',
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
        'resource': MCP_URL,
    })
    return 'https://robinhood.com/oauth?' + query

def complete_authorization(user_id: str, code: str, state: str) -> None:
    if not _enabled():
        raise BrokerUnavailable('Robinhood linking is disabled for this deployment.')
    if not code or len(code) > 4096 or not state or len(state) > 512:
        raise BrokerUnavailable('Robinhood authorization response is invalid.')
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    pending_rows = storage.read(user_id, 'broker_oauth_pending')
    row = next((item for item in pending_rows if item['key'] == state_hash), None)
    if not row:
        raise BrokerUnavailable('Robinhood authorization expired or belongs to another app session. Please try again.')
    pending = decrypt_grant(row['value']['grant'], user_id)
    storage.remove(user_id, 'broker_oauth_pending', state_hash)
    if int(pending.get('expires_at', 0)) < time.time():
        raise BrokerUnavailable('Robinhood authorization expired. Please try again.')
    try:
        response = httpx.post(TOKEN_URL, data={
            'grant_type': 'authorization_code',
            'client_id': pending['client_id'],
            'code': code,
            'redirect_uri': pending['redirect_uri'],
            'code_verifier': pending['code_verifier'],
        }, headers={'Accept': 'application/json'}, timeout=12)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data.get('access_token'), str) or not data.get('access_token') or len(data['access_token']) > 8192:
            raise ValueError('Missing access token')
        grant = {
            'access_token': data['access_token'],
            'refresh_token': data.get('refresh_token'),
            'token_type': data.get('token_type', 'Bearer'),
            'scope': data.get('scope', 'internal'),
            'expires_at': int(time.time()) + int(data.get('expires_in', 3600)),
            'client_id': pending['client_id'],
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        raise BrokerUnavailable('Robinhood authorization could not be completed. No token was saved.') from None
    storage.write(user_id, 'broker_grants', 'robinhood', {'grant': encrypt_grant(grant, user_id)})
    storage.write(user_id, 'connection_metadata', 'robinhood', {'provider': 'robinhood', 'name': 'Robinhood', 'connected_at': time.time(), 'access': 'read_only'})

def _access_token(user_id: str) -> tuple[dict, str]:
    rows = storage.read(user_id, 'broker_grants')
    row = next((item for item in rows if item['key'] == 'robinhood'), None)
    if not row:
        raise BrokerUnavailable('Connect Robinhood before refreshing your portfolio.')
    grant = decrypt_grant(row['value']['grant'], user_id)
    if grant.get('expires_at', 0) <= time.time() + 60:
        refresh_token = grant.get('refresh_token')
        if not refresh_token:
            storage.remove(user_id, 'broker_grants', 'robinhood')
            storage.remove(user_id, 'connection_metadata', 'robinhood')
            raise BrokerUnavailable('Robinhood authorization expired. Reconnect your account.')
        try:
            response = httpx.post(TOKEN_URL, data={
                'grant_type': 'refresh_token',
                'client_id': grant['client_id'],
                'refresh_token': refresh_token,
            }, headers={'Accept': 'application/json'}, timeout=12)
            response.raise_for_status()
            data = response.json()
            grant = {
                **grant,
                'access_token': data['access_token'],
                'refresh_token': data.get('refresh_token', refresh_token),
                'expires_at': int(time.time()) + int(data.get('expires_in', 3600)),
            }
            storage.write(user_id, 'broker_grants', 'robinhood', {'grant': encrypt_grant(grant, user_id)})
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise BrokerUnavailable('Robinhood authorization could not be refreshed. Reconnect your account.') from None
    return grant, grant['access_token']

def _mcp_response(response: httpx.Response) -> dict:
    response.raise_for_status()
    content_type = response.headers.get('content-type', '')
    if 'text/event-stream' in content_type:
        for line in response.text.splitlines():
            if line.startswith('data:'):
                try:
                    return json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
        raise BrokerUnavailable('Robinhood returned an unreadable portfolio response.')
    try:
        return response.json()
    except ValueError:
        raise BrokerUnavailable('Robinhood returned an unreadable portfolio response.') from None

def _mcp_call(access_token: str, tool: str, arguments: dict | None = None) -> object:
    if tool not in ALLOWED_TOOLS:
        raise PermissionError('Broker capability is not permitted')
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            init = client.post(MCP_URL, headers=headers, json={
                'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                'params': {'protocolVersion': '2025-03-26', 'capabilities': {}, 'clientInfo': {'name': 'folio-read-only', 'version': '1.0.0'}},
            })
            initialized = _mcp_response(init)
            if 'error' in initialized:
                raise BrokerUnavailable('Robinhood MCP initialization failed.')
            session_id = init.headers.get('Mcp-Session-Id')
            if session_id:
                headers['Mcp-Session-Id'] = session_id
            headers['MCP-Protocol-Version'] = str(initialized.get('result', {}).get('protocolVersion', '2025-03-26'))
            client.post(MCP_URL, headers=headers, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            result = _mcp_response(client.post(MCP_URL, headers=headers, json={
                'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                'params': {'name': tool, 'arguments': arguments or {}},
            }))
            if 'error' in result or result.get('result', {}).get('isError'):
                raise BrokerUnavailable('Robinhood did not return this portfolio data.')
            value = result.get('result', {})
            if 'structuredContent' in value:
                return value['structuredContent']
            content = value.get('content', [])
            texts = [part.get('text', '') for part in content if part.get('type') == 'text']
            for text in texts:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    continue
            return texts or value
    except (httpx.HTTPError, ValueError):
        raise BrokerUnavailable('Robinhood portfolio data is temporarily unavailable.') from None

def _mcp_data(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    data = value.get('data')
    return data if isinstance(data, dict) else value

def refresh_portfolio(user_id: str) -> dict:
    if not _enabled():
        raise BrokerUnavailable('Robinhood linking is disabled for this deployment.')
    _grant, token = _access_token(user_id)
    adapter = RobinhoodAdapter(lambda name, args: _mcp_call(token, name, args))
    accounts = adapter.call('get_accounts', {})
    # Keep only the account summaries and position fields Folio renders. Never
    # return Robinhood account numbers, transaction history, or raw MCP payloads.
    accounts_data = _mcp_data(accounts)
    account_rows = accounts_data.get('accounts', [])
    account_rows = account_rows if isinstance(account_rows, list) else []
    account_numbers = [
        item['account_number']
        for item in account_rows
        if isinstance(item, dict) and isinstance(item.get('account_number'), str) and item['account_number']
    ]
    if not account_numbers:
        raise BrokerUnavailable('Robinhood returned no accessible accounts.')
    portfolio_data = []
    position_rows = []
    for account_number in account_numbers:
        portfolio_data.append(_mcp_data(adapter.call('get_portfolio', {'account_number': account_number})))
        positions = _mcp_data(adapter.call('get_equity_positions', {'account_number': account_number}))
        rows = positions.get('positions', [])
        if isinstance(rows, list):
            position_rows.extend(rows)
    symbols = list(dict.fromkeys(
        str(item.get('symbol') or item.get('ticker') or '').upper()
        for item in position_rows
        if isinstance(item, dict) and re.fullmatch('[A-Z]{1,5}', str(item.get('symbol') or item.get('ticker') or '').upper())
    ))
    quote_prices = {}
    if symbols:
        try:
            quote_data = _mcp_data(adapter.call('get_equity_quotes', {'symbols': symbols}))
        except BrokerUnavailable:
            quote_data = {}
        quote_rows = quote_data.get('results', [])
        for item in quote_rows if isinstance(quote_rows, list) else []:
            quote = item.get('quote') if isinstance(item, dict) else None
            close = item.get('close') if isinstance(item, dict) else None
            quote = quote if isinstance(quote, dict) else {}
            close = close if isinstance(close, dict) else {}
            symbol = str(quote.get('symbol') or close.get('symbol') or '').upper()
            raw_price = next((quote.get(key) for key in ('last_trade_price', 'last_non_reg_trade_price', 'ask_price', 'bid_price') if quote.get(key) is not None), close.get('price'))
            try:
                price = float(raw_price)
            except (ValueError, TypeError):
                continue
            if re.fullmatch('[A-Z]{1,5}', symbol) and price > 0:
                quote_prices[symbol] = price
    safe_positions = []
    for item in position_rows:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get('symbol') or item.get('ticker') or '').upper()
        try:
            shares = float(item.get('quantity', item.get('shares', item.get('qty', 0))))
            market_value = float(item.get('market_value', item.get('current_value', 0)) or 0)
            price = float(item.get('current_price', item.get('price', item.get('mark_price', quote_prices.get(symbol, market_value / shares if shares else 0)))))
        except (ValueError, TypeError):
            continue
        if re.fullmatch('[A-Z]{1,5}', symbol) and shares >= 0 and price >= 0:
            safe_positions.append({'symbol': symbol, 'shares': shares, 'price': price})
    total_value = 0
    for portfolio in portfolio_data:
        raw_value = next((portfolio.get(key) for key in ('portfolio_value', 'total_portfolio_value', 'total_account_value', 'total_value', 'total_equity', 'equity') if portfolio.get(key) is not None), 0)
        try:
            total_value += max(0, float(raw_value))
        except (ValueError, TypeError):
            continue
    snapshot = {'connected': bool(account_rows), 'value': total_value, 'positions': safe_positions, 'updated_at': int(time.time())}
    storage.write(user_id, 'portfolio', 'current', snapshot)
    return snapshot

def remove_connection(user_id: str) -> None:
    # Robinhood's OAuth discovery currently advertises no revocation endpoint;
    # remove the app-held refresh grant immediately and leave provider-side
    # revocation to the user's Robinhood account settings.
    storage.remove(user_id, 'broker_grants', 'robinhood')
    storage.remove(user_id, 'connection_metadata', 'robinhood')
    storage.remove(user_id, 'portfolio')
    storage.remove(user_id, 'broker_oauth_pending')
