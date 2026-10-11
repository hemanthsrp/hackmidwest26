"""Read-only broker capability boundary; never hand this transport to an LLM."""
from collections.abc import Callable
import base64
import os
import json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ALLOWED_TOOLS = frozenset({'get_accounts', 'get_portfolio', 'get_equity_positions', 'get_equity_quotes'})

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
