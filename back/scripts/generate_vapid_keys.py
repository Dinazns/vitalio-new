#!/usr/bin/env python3
"""Generate VAPID keys for Web Push.
   Run from project root: python back/scripts/generate_vapid_keys.py
   Requires: pip install pywebpush
"""
import os
import sys

try:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from py_vapid import Vapid, b64urlencode
except ImportError:
    print("Run: pip install pywebpush")
    sys.exit(1)

script_dir = os.path.dirname(os.path.abspath(__file__))
back_dir = os.path.dirname(script_dir)
os.chdir(back_dir)

v = Vapid()
v.generate_keys()
v.save_key("vapid_private.pem")

raw = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
pub_b64 = b64urlencode(raw)
priv_path = os.path.abspath("vapid_private.pem")

print("# Add to vitalio/.env:")
print("VAPID_PUBLIC_KEY=" + pub_b64)
print("VAPID_PRIVATE_KEY=" + priv_path)
