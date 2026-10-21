"""Encrypted, researcher-only recovery of newly issued invitation codes."""
import base64
import hashlib
import json
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import HTTPException


def cipher():
    # The existing host-generated random admin secret persists across deployments.
    # An explicit secret can decouple vault encryption from bearer-token rotation.
    secret = os.environ.get('SURVEY_INVITATION_SECRET') or os.environ.get('SURVEY_ADMIN_TOKEN', '')
    if len(secret) < 32:
        raise HTTPException(503, 'Invitation code storage needs a persistent secret of at least 32 characters')
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b'synth-listening-survey',
               info=b'invitation-code-vault-v1').derive(secret.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def remember_code(db, component, code):
    checksum = hashlib.sha256(code.encode()).hexdigest()
    payload = json.dumps(dict(component=component, invite_hash=checksum, code=code)).encode()
    encrypted = cipher().encrypt(payload).decode()
    db.execute('INSERT INTO invitation_code_vault(component,invite_hash,encrypted_code) VALUES (?,?,?)',
               (component, checksum, encrypted))


def recover_code(component, checksum, encrypted):
    if checksum is None:
        return None, 'missing'
    if encrypted is None:
        return None, 'legacy_unavailable'
    try:
        payload = json.loads(cipher().decrypt(encrypted.encode()))
        code = payload['code']
        if not isinstance(code, str):
            return None, 'unreadable'
        if payload['component'] != component or payload['invite_hash'] != checksum:
            return None, 'unreadable'
        if not secrets.compare_digest(hashlib.sha256(code.encode()).hexdigest(), checksum):
            return None, 'unreadable'
        return code, 'available'
    except HTTPException:
        return None, 'key_unavailable'
    except (InvalidToken, ValueError, TypeError, KeyError, UnicodeError):
        return None, 'unreadable'
