import asyncio
from app.database import SessionLocal
from app.models import User, MarketResearchReport


async def seed():
    async with SessionLocal() as db:
        users = [
            User(org_id=1, email="alice@org1.com"),
            User(org_id=1, email="bob@org1.com"),
            User(org_id=1, email="carol@org1.com"),

            User(org_id=2, email="dave@org2.com"),
            User(org_id=2, email="eve@org2.com"),
            User(org_id=2, email="frank@org2.com"),
        ]
        db.add_all(users)
        await db.flush()

        report = MarketResearchReport(
            user_id=users[0].id,
            company_name="BlueKnight",
            company_url="https://blueknight.io",
            sections={
                "executive_summary": {"text": "BlueKnight is a market research platform that generates structured reports for companies."},
                "market_size": {"text": "The market size for market research platforms is $10B."},
                "key_trends": {"text": "AI adoption is accelerating."},
                "competitive_landscape": {"text": "Three major players dominate the market."},
            },
        )
        db.add(report)
        await db.commit()
        print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())