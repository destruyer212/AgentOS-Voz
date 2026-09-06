from fastapi import APIRouter

from app.api.v1 import (
    agent,
    agent_llm_proxy,
    analytics,
    conversations,
    customers,
    invoicing,
    orders,
    products,
    system,
    telephony,
    telephony_telnyx,
    telephony_telnyx_stream,
)

api_router = APIRouter()
api_router.include_router(products.router)
api_router.include_router(customers.router)
api_router.include_router(orders.router)
api_router.include_router(invoicing.router)
api_router.include_router(analytics.router)
api_router.include_router(agent.router)
api_router.include_router(agent_llm_proxy.router)
api_router.include_router(conversations.router)
api_router.include_router(system.router)
api_router.include_router(telephony.router)
api_router.include_router(telephony_telnyx.router)
api_router.include_router(telephony_telnyx_stream.router)
