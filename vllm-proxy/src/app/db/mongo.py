import os

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.getenv(
    "MONGO_URI", "mongodb://admin:uf9aVein8Oon3opi@10.10.20.208:27017/"
)
MONGO_DB = os.getenv("MONGO_DB", "vllm_metrics")

client = AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB]

mongo_metrics = db["chat_completions_metrics"]
mongo_error_requests = db["error_requests"]
