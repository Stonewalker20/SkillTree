from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

_client: AsyncIOMotorClient | None = None

async def connect_to_mongo() -> None:
    global _client
    _client = AsyncIOMotorClient(settings.mongo_uri)
    #remove eventually - just for testing connection on startup
    print(f"[Mongo] Connected uri={settings.mongo_uri} db={settings.mongo_db}")


async def close_mongo_connection() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None

def get_db() -> AsyncIOMotorDatabase:
    if _client is None:
        raise RuntimeError("Mongo client is not initialized. Did startup run?")
    return _client[settings.mongo_db]




