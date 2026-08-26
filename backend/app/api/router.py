from fastapi import APIRouter

from app.api.v1 import agent, customers, orders, products, system, telephony, telephony_telnyx

api_router = APIRouter()
api_router.include_router(products.router)
api_router.include_router(customers.router)
api_router.include_router(orders.router)
api_router.include_router(agent.router)
api_router.include_router(system.router)
api_router.include_router(telephony.router)
api_router.include_router(telephony_telnyx.router)
