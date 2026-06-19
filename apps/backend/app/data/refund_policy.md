# WORPODD Refund Policy (Strict)

**Version:** 1.0 · **Effective:** 2026-01-01
**Scope:** All WORPODD retail orders. This document is the authoritative
refund policy. The automated support agent enforces these clauses exactly;
it is **not authorized to make exceptions**, override a denial, or approve a
refund that violates any clause below.

## Guiding principles
1. Refunds are a customer right when policy conditions are met — and **only** then.
2. The agent's job is to gather facts and apply the policy, not to negotiate it.
3. When in genuine ambiguity, escalate to manual review. Never guess toward approval.

---

## Clauses

### R1 — Standard return window
Returns are eligible within **30 calendar days** of the delivery date.
Requests after 30 days are **denied** (defective items excepted — see R8).

### R2 — Item condition
Returned items must be **unused**, with **original tags and packaging** intact.
Items returned used or with missing tags/packaging are subject to a partial
refund at WORPODD's discretion (see R5) or denied if condition is unacceptable.

### R3 — Non-refundable categories
The following are **never refundable** (unless legally required):
- Final sale / clearance items
- Perishables (food, flowers)
- Personalized or custom-made items
- Intimate apparel (underwear, swimwear worn)
- Digital downloads, **once accessed**
- Gift cards

### R4 — Original payment method
Refunds are issued to the **original payment method only**. No cash, no
third-party transfer, no redirect to a different card. A customer requesting
refund to a different account is **denied** and directed to their bank.

### R5 — Partial refund (missing packaging)
If an otherwise-eligible item is returned with **missing packaging only**
(item still unused), WORPODD may issue a **partial refund** (default 85% of
item price) at its discretion. This is never a full denial and never a full
refund.

### R6 — Restocking fee
A **15% restocking fee** applies to **electronics and furniture** with an item
price **over $200**. The fee is deducted from the refund amount.

### R7 — Shipping non-refundable
Original shipping charges are **non-refundable**, **except** when the return
is due to a WORPODD error (defective or incorrect item — see R8). Return
shipping is the customer's responsibility unless WORPODD was at fault.

### R8 — Defective / incorrect items
Items that arrive **defective, damaged, or incorrect** qualify for a **full
refund or replacement**, with **no restocking fee** and **return shipping
covered**, within the 30-day window. Defective claims require evidence
(photo/confirmation collected by the agent).

### R9 — Gift returns
Items received as a **gift** are refunded as **store credit only**, never to
the original payment method.

### R10 — Refund abuse
A customer's refund history is checked against abuse thresholds (trailing
90 days):
- **More than 3** refunds in 90 days → **manual review** (held, not auto-approved)
- **More than 5** refunds in 90 days → **denied** as suspected abuse

### R11 — Order status
Only orders with status **`paid`** are refundable. Orders that are
`pending`, `cancelled`, or `refunded` are **ineligible**. An order that is
already fully refunded cannot be refunded again.

### R12 — Price adjustment window
Requests to refund the difference after a price drop are honored only within
**7 calendar days** of purchase. After that, price-adjustment refunds are denied.

### R13 — Bundles
Items sold as a **bundle** must be returned **as a complete bundle**. Partial
returns of a bundled item are **denied**.

---

## Agent operating rules
- The agent collects the customer identifier and order number first.
- The agent may ask clarifying questions (condition, defective evidence, etc.).
- The agent **must** present the verdict the policy engine returns, and cite the
  specific clause (R1–R13) that drove the decision.
- The agent **must not** promise a refund the policy engine has not approved.
- On `manual_review` (R10), the agent informs the customer their case is being
  reviewed and no immediate refund is issued.

## Decisions the engine can return
| Verdict | Meaning |
|---|---|
| `approved` | Full refund, conditions met |
| `approved_partial` | Refund less restocking/packaging deduction (R5/R6) |
| `approved_store_credit` | Gift return, store credit only (R9) |
| `manual_review` | Held for human review (R10 lower threshold, or genuine ambiguity) |
| `denied` | Policy violation — cite the clause |
