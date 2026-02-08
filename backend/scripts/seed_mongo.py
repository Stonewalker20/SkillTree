import os
import json
import asyncio
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "data" / "seed"

def load_json(filename: str):
    path = SEED_DIR / filename
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

async def main():
    load_dotenv(ROOT / ".env")  # repo root .env
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    mongo_db = os.getenv("MONGO_DB", "skilltree")

    client = AsyncIOMotorClient(mongo_uri)
    db = client[mongo_db]

    skills = load_json("skills.json")
    jobs = load_json("jobs.json")
    evidence = load_json("evidence.json")

    # repeatable dev seed
    for col in ["skills", "jobs", "evidence"]:
        await db[col].delete_many({})

    if skills:
        await db["skills"].insert_many(skills)
    if jobs:
        await db["jobs"].insert_many(jobs)
    if evidence:
        await db["evidence"].insert_many(evidence)

    print("Seed complete:", {"skills": len(skills), "jobs": len(jobs), "evidence": len(evidence)})

    client.close()

if __name__ == "__main__":
    asyncio.run(main())

