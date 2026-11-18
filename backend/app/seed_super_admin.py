"""One-time script to seed the super admin user into MongoDB."""

import asyncio

from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app._core.settings import settings
from app.components.auth.models import User
from app.components.common.schemas import Role, UserStatus


async def seed():
    client = AsyncIOMotorClient(settings.MONGO_URI)
    await init_beanie(database=client[settings.MONGO_DB_NAME], document_models=[User])

    existing = await User.find_one(User.role == Role.SUPER_ADMIN)
    if existing:
        print(f"Super admin already exists: {existing.email}")
        client.close()
        return

    admin = User(
        email=settings.SUPER_ADMIN_EMAIL,
        role=Role.SUPER_ADMIN,
        status=UserStatus.ACTIVE,
        full_name="Super Admin",
    )
    await admin.insert()
    print(f"Super admin created: {admin.email}")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
