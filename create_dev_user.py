"""
Create or update the local development student account.

Run after migrations:

    uv run python create_dev_user.py
"""
import asyncio

from app.dev_seed import DEV_EMAIL, seed_dev_user


if __name__ == "__main__":
    asyncio.run(seed_dev_user())
    print(f"Development user ensured: {DEV_EMAIL}")
