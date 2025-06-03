import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "vllm_metrics")

client = AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB]

mongo_metrics = db["chat_completions_metrics"]
mongo_error_requests = db["error_requests"]

async def insert_document():
    result = await mongo_metrics.insert_one({})
    print(f"Inserted document with ID: {result.inserted_id}")
    return result

# Run the async function
if __name__ == "__main__":
    asyncio.run(insert_document())
