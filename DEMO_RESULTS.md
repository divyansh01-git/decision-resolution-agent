# Demonstration Results

These are real CLI outputs of the offline (deterministic) test agent, generated with Python 3. All transactions and notifications are local simulations. Real Gemini/OpenAI providers require their respective API keys and available quotas; the live provider endpoints have not been exercised in these local results. Gemini adapter tests use mocked API replies.

## Out of stock → refund

Command: `python3 main.py --order ORD-1001 --reset-db`

```text

DECISION-MAKING RESOLUTION AGENT
Mode: offline | Status: completed

TOOL EXECUTION TRACE
  Cycle 1: lookup_order -> SUCCESS
    {"success": true, "action": "lookup_order", "data": {"order_id": "ORD-1001", "customer_name": "Maya Sharma", "customer_email": "maya@example.com", "item_id": "SKU-HEADPHONES", "item_name": "Wireless Headphones", "order_status": "delivered", "exchange_eligible": true, "amount_inr": "3499.00", "payment_method": "Card ending 1234"}}
  Cycle 2: inspect_inventory -> SUCCESS
    {"success": true, "action": "inspect_inventory", "data": {"item_id": "SKU-HEADPHONES", "stock_count": 0, "available": false}}
  Cycle 3: initiate_refund -> SUCCESS
    {"success": true, "action": "initiate_refund", "data": {"order_id": "ORD-1001", "refund_reference": "RFD-ORD-1001", "amount_inr": "3499.00", "payment_method": "Card ending 1234", "already_processed": false, "simulated": true}}
  Cycle 4: send_notification -> SUCCESS
    {"success": true, "action": "send_notification", "data": {"order_id": "ORD-1001", "email": "maya@example.com", "delivery_status": "mock_saved", "already_processed": false, "simulated": true}}

CUSTOMER RESPONSE
I'm sorry about your Wireless Headphones. For ORD-1001, a refund of ₹3499.00 to Card ending 1234 has been recorded (reference RFD-ORD-1001). A confirmation has been saved to the mock email outbox for maya@example.com. This is a simulation: no actual money, shipment or email was sent.
```

## In stock → exchange

Command: `python3 main.py --order ORD-1002 --reset-db`

```text

DECISION-MAKING RESOLUTION AGENT
Mode: offline | Status: completed

TOOL EXECUTION TRACE
  Cycle 1: lookup_order -> SUCCESS
    {"success": true, "action": "lookup_order", "data": {"order_id": "ORD-1002", "customer_name": "Aarav Mehta", "customer_email": "aarav@example.com", "item_id": "SKU-SPEAKER", "item_name": "Bluetooth Speaker", "order_status": "delivered", "exchange_eligible": true, "amount_inr": "2499.00", "payment_method": "UPI ending 5678"}}
  Cycle 2: inspect_inventory -> SUCCESS
    {"success": true, "action": "inspect_inventory", "data": {"item_id": "SKU-SPEAKER", "stock_count": 4, "available": true}}
  Cycle 3: confirm_exchange -> SUCCESS
    {"success": true, "action": "confirm_exchange", "data": {"order_id": "ORD-1002", "exchange_reference": "EXC-ORD-1002", "item_id": "SKU-SPEAKER", "already_processed": false}}
  Cycle 4: send_notification -> SUCCESS
    {"success": true, "action": "send_notification", "data": {"order_id": "ORD-1002", "email": "aarav@example.com", "delivery_status": "mock_saved", "already_processed": false, "simulated": true}}

CUSTOMER RESPONSE
I'm sorry about your Bluetooth Speaker. For ORD-1002, a replacement exchange has been recorded (reference EXC-ORD-1002). A confirmation has been saved to the mock email outbox for aarav@example.com. This is a simulation: no actual money, shipment or email was sent.
```

## Invalid order → friendly error

Command: `python3 main.py --order ORD-9999 --reset-db`

```text

DECISION-MAKING RESOLUTION AGENT
Mode: offline | Status: completed

TOOL EXECUTION TRACE
  Cycle 1: lookup_order -> ERROR
    {"success": false, "action": "lookup_order", "error": {"code": "ORDER_NOT_FOUND", "message": "Order 'ORD-9999' was not found. Please verify the order ID."}}

CUSTOMER RESPONSE
I couldn't find ORD-9999. Please verify the order ID and try again.
```

## Interactive evaluator workflow

Run `python3 main.py --interactive --reset-db`, then enter: 

```text
Customer> My order ORD-1001 arrived damaged. Can I get a replacement?
Customer> My order ORD-1002 arrived broken.
Customer> My order ORD-9999 is damaged.
Customer> exit
```

The interactive CLI prints the tool trace and final answer for each message. The CLI demonstration was verified by automated subprocess tests. All transactions and notifications are simulated.

**Automated tests:** 18 tests passing, including 2 tests of real terminal input through the interactive CLI.
