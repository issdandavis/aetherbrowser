# Aether portal and service map

The website is the public front door. It may explain an offer, sell access once
checkout and entitlement are connected, or route a visitor into a bounded tool.
It is not the execution engine and must not imply that an unconnected checkout
already delivers a product.

## One service, one job

| Surface | Job | Must not do |
|---|---|---|
| Website / Aether Hall | Discovery, explanation, offer selection, tool entry | Hold execution credentials or claim unverified capability |
| AetherDesk | Local control plane, approval UI, routing, receipt display | Silently approve remote writes |
| AetherBrowser kernel | Observe, plan, approve, dispatch, verify, receipt | Browse or mutate outside the fixed allowlist |
| GitHub | Versioned source and reviewable history | Store runtime secrets or private training data |
| Hugging Face | Public, content-addressed, secret-free release and evidence mirror | Receive competition test data, store secrets/private data, or become an undeclared inference dependency |
| Kaggle | Private offline CPU validation and competition-specific work in its own lane | Consume competition submission slots for infrastructure checks |
| Lightning | Disposable compatibility checks or explicitly bounded training | Leave paid compute running after the receipt is written |

## Portal transaction

1. The website identifies the offer and the exact tool route.
2. AetherDesk shows capabilities, price or entitlement state, and the requested
   action before execution.
3. The kernel observes the current page and produces a stale-detectable plan.
4. Governance denies secrets and remote writes by default; an authorized human
   approval is attached when a supported mutation is intended.
5. The fixed dispatcher runs the action.
6. Verification compares the result with the plan.
7. A hash-chained receipt and save-slot checkpoint are returned to AetherDesk.
8. The website may show the result or delivery state, but never the secret input.

The current browser offer is a **verified preview**. Its tool route works locally,
but checkout is intentionally marked `checkout_connected: false`. Connecting a
payment provider later is a separate, auditable step at the entitlement boundary;
it does not change the browser kernel's execution authority.

## Delivery invariant

A sale is complete only when all three statements are true:

- payment or entitlement is verified;
- the promised tool route is reachable for that customer; and
- the customer receives a receipt naming the delivered version and result.

This separates marketing, money, execution, and evidence while still letting the
website act as the portal that joins them.
