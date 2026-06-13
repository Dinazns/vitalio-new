"""Generate a Fernet key for FIELD_ENCRYPTION_KEY in back/.env"""
from cryptography.fernet import Fernet

if __name__ == "__main__":
    key = Fernet.generate_key().decode("ascii")
    print("Add to back/.env (and Render environment):")
    print(f"FIELD_ENCRYPTION_KEY={key}")
