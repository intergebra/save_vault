import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_LEN_BYTES = 32  # 256 bits
NONCE_LEN_BYTES = 12


def generate_key_hex() -> str:
    """Generate a new random 256-bit key, returned as a 64-char hex string."""
    return os.urandom(KEY_LEN_BYTES).hex()


def key_from_hex(hex_str: str) -> bytes:
    hex_str = (hex_str or "").strip()
    try:
        key = bytes.fromhex(hex_str)
    except ValueError:
        raise ValueError("Key must be a valid hex string.")
    if len(key) != KEY_LEN_BYTES:
        raise ValueError(
            f"Key must be exactly 256 bits (64 hex characters). Got {len(key) * 8} bits."
        )
    return key


def encrypt_chunk(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt with a fresh random nonce. Returns nonce || ciphertext(+tag)."""
    aesgcm = AESGCM(key)
    nonce = os.urandom(NONCE_LEN_BYTES)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ct


def decrypt_chunk(key: bytes, data: bytes) -> bytes:
    if len(data) < NONCE_LEN_BYTES:
        raise ValueError("Malformed encrypted payload.")
    aesgcm = AESGCM(key)
    nonce, ct = data[:NONCE_LEN_BYTES], data[NONCE_LEN_BYTES:]
    return aesgcm.decrypt(nonce, ct, None)
