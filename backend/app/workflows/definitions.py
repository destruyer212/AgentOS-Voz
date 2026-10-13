"""Definiciones de workflow embebidas. En el sprint del builder visual esto
pasara a vivir en la tabla `workflows`/`workflow_versions`; por ahora el
motor ya es real, solo falta el editor."""

from app.workflows.models import WorkflowDefinition, WorkflowStep

RESTAURANT_ORDER_FULFILLMENT = WorkflowDefinition(
    key="restaurant_order_fulfillment",
    name="Fulfillment de pedido de restaurante",
    steps=[
        WorkflowStep(
            key="require_items",
            type="condition",
            check_path="items",
            fail_message="No hay items para procesar el pedido.",
        ),
        WorkflowStep(
            key="create_order",
            type="tool",
            tool="orders.create_confirmed",
            input_map={
                "customer_id": "customer_id",
                "conversation_id": "conversation_id",
                "requested_time": "requested_time",
                "fulfillment_type": "fulfillment_type",
                "delivery_address": "delivery_address",
                "payment_method": "payment_method",
                "payment_reference": "payment_reference",
                "items": "items",
            },
            output_key="order_result",
        ),
        WorkflowStep(
            key="schedule_delivery",
            type="tool",
            tool="orders.schedule_delivery",
            input_map={"order_id": "order_result.order.id", "requested_time": "requested_time"},
            output_key="schedule_result",
        ),
        WorkflowStep(
            key="send_confirmation",
            type="tool",
            tool="notifications.send_confirmation",
            input_map={"order_id": "order_result.order.id", "customer_id": "customer_id", "channel": "channel"},
            output_key="notification_result",
        ),
        WorkflowStep(key="close_call", type="end"),
    ],
)
