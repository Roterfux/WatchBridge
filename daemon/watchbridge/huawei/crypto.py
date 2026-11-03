# WatchBridge - Huawei Watch GT 5 companion for Sailfish OS
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Ported from Gadgetbridge (HuaweiCrypto.java, CryptoUtils.java),
# Copyright (C) 2021-2024 Andreas Shimokawa, Damien Gaignon, José Rebelo, Martin.JM.
# Translated to Python and modified for WatchBridge, 2026. See NOTICE.md.
"""Huawei link-layer cryptography helpers."""

import hashlib
import hmac
import os

from . import aes

SECRET_KEY_1_V1 = bytes([0x6F, 0x75, 0x6A, 0x79, 0x6D, 0x77, 0x71, 0x34, 0x63, 0x6C, 0x76, 0x39, 0x33, 0x37, 0x38, 0x79])
SECRET_KEY_2_V1 = bytes([0x62, 0x31, 0x30, 0x6A, 0x67, 0x66, 0x64, 0x39, 0x79, 0x37, 0x76, 0x73, 0x75, 0x64, 0x61, 0x39])
SECRET_KEY_1_V23 = bytes([0x55, 0x53, 0x86, 0xFC, 0x63, 0x20, 0x07, 0xAA, 0x86, 0x49, 0x35, 0x22, 0xB8, 0x6A, 0xE2, 0x5C])
SECRET_KEY_2_V23 = bytes([0x33, 0x07, 0x9B, 0xC5, 0x7A, 0x88, 0x6D, 0x3C, 0xF5, 0x61, 0x37, 0x09, 0x6F, 0x22, 0x80, 0x00])

DIGEST_SECRET_V1 = bytes([0x70, 0xFB, 0x6C, 0x24, 0x03, 0x5F, 0xDB, 0x55, 0x2F, 0x38, 0x89, 0x8A, 0xEE, 0xDE, 0x3F, 0x69])
DIGEST_SECRET_V2 = bytes([0x93, 0xAC, 0xDE, 0xF7, 0x6A, 0xCB, 0x09, 0x85, 0x7D, 0xBF, 0xE5, 0x26, 0x1A, 0xAB, 0xCD, 0x78])
DIGEST_SECRET_V3 = bytes([0x9C, 0x27, 0x63, 0xA9, 0xCC, 0xE1, 0x34, 0x76, 0x6D, 0xE3, 0xFF, 0x61, 0x18, 0x20, 0x05, 0x53])

MESSAGE_RESPONSE = b"\x01\x10"
MESSAGE_CHALLENGE = b"\x01\x00"
MESSAGE_CHALLENGE_V4 = b"\x04\x00"

ENCRYPTION_COUNTER_MAX = 0xFFFFFFFF


def hexstr(data):
    """Uppercase hex, matching Gadgetbridge's GB.hexdump / StringUtils.bytesToHex."""
    return bytes(data).hex().upper()


def generate_nonce():
    return os.urandom(16)


def hmac_sha256(key, message):
    return hmac.new(bytes(key), bytes(message), hashlib.sha256).digest()


def sha256(data):
    return hashlib.sha256(bytes(data)).digest()


def hkdf_sha256(secret, salt, info, length):
    prk = hmac_sha256(salt, secret)
    out = b""
    block = b""
    counter = 1
    while len(out) < length:
        block = hmac_sha256(prk, block + bytes(info) + bytes([counter]))
        out += block
        counter += 1
    return out[:length]


def pbkdf2_sha256(password, salt, iterations, length_bits):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations, length_bits // 8)


def encrypt(use_gcm, message, key, iv):
    if use_gcm:
        return aes.gcm_encrypt(key, iv, message)
    return aes.cbc_encrypt(key, iv, message)


def decrypt(use_gcm, message, key, iv):
    if use_gcm:
        return aes.gcm_decrypt(key, iv, message)
    return aes.cbc_decrypt(key, iv, message)


def initialization_vector(counter):
    """Returns (iv, new_counter) for counter based IVs."""
    counter = 1 if counter == ENCRYPTION_COUNTER_MAX else counter + 1
    iv = generate_nonce()[:12] + (counter & 0xFFFFFFFF).to_bytes(4, "big")
    return iv, counter


class HuaweiCrypto:
    """Digest helpers used by the 'normal' and 'HiChain Lite' auth modes."""

    def __init__(self, auth_version, auth_algo=0, device_support_type=0, auth_mode=0):
        self.auth_version = auth_version
        self.auth_algo = auth_algo
        self.device_support_type = device_support_type
        self.auth_mode = auth_mode

    def _digest_secret(self):
        if self.auth_version in (1, 4):
            return DIGEST_SECRET_V1
        if self.auth_version == 2:
            return DIGEST_SECRET_V2
        return DIGEST_SECRET_V3

    def compute_digest(self, message, nonce):
        step1 = hmac_sha256(self._digest_secret() + message, nonce)
        return hmac_sha256(step1, nonce) + step1

    def compute_digest_hichain_lite(self, message, key, nonce):
        hash_key = sha256(hexstr(key).encode("utf-8"))
        secret = bytes(a ^ b for a, b in zip(hash_key, self._digest_secret()))
        msg = secret + message
        if self.auth_algo == 0x01:
            step1 = pbkdf2_sha256(hexstr(msg), hexstr(nonce), 0x3E8, 0x100)
        else:
            step1 = hmac_sha256(msg, nonce)
        return hmac_sha256(step1, nonce) + step1

    def _digest(self, message, secret_key, nonce, default_message):
        if self.auth_mode == 0x02:
            if secret_key is None:
                return None
            if self.auth_version == 0x02:
                key = bytes(secret_key) + message
                return hmac_sha256(key, nonce) + key
            return self.compute_digest_hichain_lite(message, secret_key, nonce)
        return self.compute_digest(default_message, nonce)

    def digest_challenge(self, secret_key, nonce):
        default = MESSAGE_CHALLENGE_V4 if self.auth_version == 4 else MESSAGE_CHALLENGE
        return self._digest(MESSAGE_CHALLENGE, secret_key, nonce, default)

    def digest_response(self, secret_key, nonce):
        return self._digest(MESSAGE_RESPONSE, secret_key, nonce, MESSAGE_RESPONSE)

    def create_secret_key(self, mac_address):
        k1, k2 = (SECRET_KEY_1_V1, SECRET_KEY_2_V1) if self.auth_version == 1 else (SECRET_KEY_1_V23, SECRET_KEY_2_V23)
        mac_key = (mac_address.replace(":", "") + "0000").encode("utf-8")
        mixed = bytes(((a << 4) ^ b) & 0xFF for a, b in zip(k1, k2))
        mixed_hash = sha256(mixed)
        final = bytes(((mixed_hash[i] >> 6) ^ mac_key[i]) & 0xFF for i in range(16))
        return sha256(final)[:16]

    @staticmethod
    def encrypt_bonding_key(encrypt_method, data, key, iv):
        return encrypt(encrypt_method == 0x01, data, key, iv)

    def decrypt_pin_code(self, encrypt_method, message, iv):
        return decrypt(encrypt_method == 0x01, message, self._digest_secret(), iv)
