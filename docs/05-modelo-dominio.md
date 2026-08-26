# Modelo De Dominio Inicial

## Entidades

```text
Tenant
  Branch
  User
  Agent
    AgentProfile
    AgentVoice
    AgentKnowledge
    Workflow binding
  Customer
    CustomerPhone
    Address
  Product
    ProductVariant
  Inventory
  Order
    OrderItem
  Call
    Conversation
    Message
  Workflow
    WorkflowVersion
    WorkflowRun
  ToolCall
  Integration
  AuditLog
```

## Tablas candidatas

- tenants
- branches
- users
- agents
- agent_profiles
- customers
- customer_phones
- addresses
- products
- product_variants
- inventory
- orders
- order_items
- calls
- conversations
- messages
- workflows
- workflow_versions
- workflow_runs
- tool_calls
- integrations
- audit_logs

## Campos obligatorios por entidad empresarial

```text
id
tenant_id
created_at
updated_at
```

Cuando aplique:

```text
deleted_at
created_by
updated_by
status
metadata
```

## Pedido restaurante

Estados sugeridos:

```text
draft
pending_confirmation
confirmed
preparing
ready
scheduled
delivered
cancelled
failed
```

## Call / conversation

Datos minimos:

- tenant_id
- agent_id
- customer_id opcional
- channel
- phone_number opcional
- started_at
- ended_at
- duration_seconds
- transcript
- detected_intents
- outcome
- error_summary
