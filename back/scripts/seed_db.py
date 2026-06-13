import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

env_path = ".env" if os.path.exists(".env") else "../.env"
load_dotenv(env_path)

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_IDENTITY_DB = os.getenv("MONGODB_IDENTITY_DB", "Vitalio_Identity")


def main():
    user_id_auth = os.getenv("SEED_USER_ID_AUTH", "")
    device_id = os.getenv("SEED_DEVICE_ID", os.getenv("DEVICE_ID", "SIM-ESP32-001"))

    if not user_id_auth:
        raise RuntimeError("SEED_USER_ID_AUTH is required in .env to seed users_devices")

    try:
        client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
    except PyMongoError as e:
        raise RuntimeError(f"Cannot connect to MongoDB: {e}") from e

    db = client[MONGODB_IDENTITY_DB]
    db.users_devices.create_index("user_id_auth", unique=True)

    db.users_devices.update_one(
        {"user_id_auth": user_id_auth},
        {"$set": {"user_id_auth": user_id_auth, "device_id": device_id}},
        upsert=True,
    )

    print(f"Seed OK: {user_id_auth} -> {device_id}")


if __name__ == "__main__":
    main()
