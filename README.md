# Ahaa Kitchen Subscription Management

Requirements and implementation plan for a private food credit application for [Ahaa Kitchen](https://ahaakitchen.com/).

**Status:** Documentation only. The record-keeping application and subdomain have not been built, and WhatsApp messaging has not been connected. No payment integration is planned.

**Records only — no payment integration:** This application records money the owner has already received or refunded outside the software. Do not integrate Razorpay, Stripe, PayPal, card processing, bank APIs, checkout, or payment webhooks. It never collects, transfers, charges, or refunds money. WhatsApp is a messaging integration only.

## 1. Purpose

Customers pay Ahaa Kitchen $200 and receive $240 in food credit with **unlimited validity**. The owner registers customers, records payments, records food collections, and manages refunds. Saving a payment or food order automatically triggers a WhatsApp confirmation to the customer.

Only the owner uses this application. Customers do not need an account, application installation, or website login.

Although the project is called subscription management, the offer is a prepaid food credit plan with no expiry and no automatic recurring charge.

## 2. Confirmed business rules

| Topic | Required behavior |
| --- | --- |
| Currency | US dollars (USD) |
| Payment | Customer pays $200 externally; owner records the received payment |
| Payment processing | None; all payment and refund entries are manual records only |
| Food credit | Grant $240: $200 paid value plus $40 promotional bonus |
| Validity | Unlimited; credit never expires automatically |
| Unused balance | Remains available until spent or changed through an owner-authorized refund/adjustment |
| Food collection | Owner enters item names, quantities, and final tax-inclusive values |
| Tax | Included in the entered bill values; no separate tax calculation or extra tax charge |
| Insufficient balance | Block the entire order and show **Not sufficient balance** |
| Split payment | Not supported; do not accept a separate payment for the shortfall as part of an order |
| Renewal | When credit is exhausted, the customer can immediately pay $200 again and receive a new $240 credit grant |
| Refunds | Allowed; only the owner can authorize, record, or correct them |
| Payment confirmation | Automatically send WhatsApp after payment and credit are successfully saved |
| Order receipt | Automatically send WhatsApp after order and deduction are successfully saved |
| Access | Owner only; public registration and customer access disabled |
| Branding | Use the existing ahaakitchen.com color palette, logo, and typography |

There are no monthly periods, expiry dates, expiry deductions, rollover jobs, or scheduled renewals. A customer can use the credit over any length of time.

### Example

| Event | Cash received | Food credit movement | Available balance |
| --- | ---: | ---: | ---: |
| Customer pays and enrolls | $200.00 | +$240.00 | $240.00 |
| Collects food | — | -$40.00 | $200.00 |
| Collects more food | — | -$200.00 | $0.00 |
| Immediately pays and renews | $200.00 | +$240.00 | $240.00 |

Payment value and food credit are different: $240 of granted credit does not mean $240 of cash received.

## 3. Address and private access

- Requested address: `https://subsription.ahaakitchen.com`.
- The requested spelling is retained. The corrected alternative is `https://subscription.ahaakitchen.com`; final spelling remains to be chosen before DNS configuration.
- Use a separate private application under the Ahaa Kitchen domain, with HTTPS.
- Require owner authentication and authorization for all customer and financial operations.
- Create the owner account through a controlled setup procedure; disable public signup.
- Customers cannot view accounts, place orders, change credit, or request refunds through this application.
- Use `noindex`, but enforce privacy through authentication rather than hidden URLs.
- The marketing website can remain independently hosted.

## 4. Customer registration

Required fields:

- Full name.
- Email address.
- Phone number with country code.
- WhatsApp number, defaulting to the phone number, with an option to use a different number.
- Notification permission, including consent date and how it was obtained.

Optional fields: internal notes and an owner-assigned customer reference.

Validate email and international phone formatting. Warn about duplicate names/contact details. A shared family number requires an explicit owner override and must not merge customer balances.

The customer profile displays current balance, payments, credit grants, food collections, refunds, adjustments, and WhatsApp history. Search by name, phone, email, or customer reference.

## 5. Payment and enrollment workflow

1. Find or create the customer.
2. Choose **Pay $200 / Get $240 Food Credit**.
3. Confirm that the $200 payment has actually been received.
4. Record payment method, date/time, and optional external reference.
5. Review $200 received, $40 bonus, and $240 food credit.
6. Click **Save Payment & Enroll**.
7. Save payment, credit grant, ledger entries, and notification job in one database transaction.
8. Automatically send the payment confirmation to the customer's WhatsApp number when permission is recorded.

For the fixed offer, require exactly $200 received. Partial or mismatched payments must not grant $240. The owner records cash, a transfer, or an externally processed card payment; saving does not charge a card or detect bank deposits automatically.

The save action means **record a payment already received**, not pay now. There is no customer checkout, payment link, gateway SDK, payment verification API, or online payment status synchronization. The owner's confirmation is the source of the recorded payment status. Any payment method/reference field is descriptive bookkeeping information only.

### Renewal

When available credit reaches zero, allow **Renew Now** immediately. Recording a new $200 payment grants a new $240 without waiting for any date. Keep all previous payments, grants, and orders.

**Proposed first-version scope:** renewal is enabled at zero balance. Additional $200 top-ups while a positive balance remains are not yet confirmed; do not silently discard or replace an existing balance. If such top-ups are added later, preserve the previous credit and define the allocation rules explicitly.

### Payment WhatsApp example

```text
Ahaa Kitchen
Hi Ravi, your payment has been recorded.

Payment reference: AK-PAY-000123
Payment received: $200.00 USD
Bonus credit: $40.00 USD
Food credit added: $240.00 USD
Available balance: $240.00 USD
Validity: No expiry

Thank you for choosing Ahaa Kitchen!
```

Include payment date/time in the production template. Use the same automatic confirmation for every paid renewal. A failed WhatsApp message does not undo the saved payment or cause another credit grant.

## 6. Food order workflow

1. Search for and select the customer.
2. Display their current available credit prominently.
3. Enter food item names, quantities, and final tax-inclusive unit amounts.
4. Calculate the total and preview the remaining balance.
5. Click **Save Order**.
6. Validate balance on the server, save the itemized order, deduct credit, and queue the WhatsApp receipt atomically.
7. Display the saved order, updated balance, and notification status.

No separate send action, WhatsApp chat opening, copying text, or phone confirmation is required.

| Item | Quantity | Tax-inclusive unit amount | Line total |
| --- | ---: | ---: | ---: |
| Chicken Biryani | 1 | $18.00 | $18.00 |
| Paneer Curry | 1 | $14.00 | $14.00 |
| Naan | 2 | $4.00 | $8.00 |
| **Final bill amount** | | | **$40.00** |

Before: **$240.00**. Deduct: **$40.00**. Remaining: **$200.00**.

The entered values already include applicable taxes. Do not calculate or add tax separately. The final deduction must equal the sum of the entered line totals. For a bill total that differs from the item sum, require the owner to correct the item values before saving; do not silently add an unexplained adjustment.

### Insufficient balance

For a $40 order against a $30 balance, show:

```text
Not sufficient balance.
Available balance: $30.00
Order total: $40.00
Shortfall: $10.00
```

Do not save a financial order, deduct any credit, or send a receipt for the rejected order. No negative balance or split payment is allowed. The owner can revise the food order to fit the balance. Renewal at zero is supported; topping up a positive balance remains an open scope decision.

### Order WhatsApp example

```text
Ahaa Kitchen
Hi Ravi, your food collection has been recorded.

Order: AK-000123
Collected: Oct 30, 2026, 12:30 PM CDT
Chicken Biryani x1 - $18.00
Paneer Curry x1 - $14.00
Naan x2 - $8.00

Order total: $40.00 USD
Remaining balance: $200.00 USD
Validity: No expiry

Thank you for choosing Ahaa Kitchen!
```

Allow multiple food collections on the same day while sufficient balance remains. Item names are manually entered initially; a reusable catalog can be added later.

## 7. Owner-controlled refunds and corrections

Refunds are allowed and controlled exclusively by the owner. Customers cannot change or approve them. Separate **returning money** from **correcting a food deduction**.

### Payment refund

The owner opens the original payment and records:

- Cash refund amount.
- Food credit to remove, shown separately from cash being refunded.
- Reason.
- Refund method and external reference where available.
- Date/time money was actually returned.

Show the balance before/after and require an explicit owner confirmation before saving. Record the refund and credit debit atomically, together with an audit entry and notification job. Saving a refund records money returned externally; the application does not issue a bank/card refund itself.

Label the action **Record Refund** so its bookkeeping purpose is clear. The owner returns the money separately and then records what was returned. There is no refund API or connection to a payment processor.

**Refund policy remains owner-decided:** there is no automatic formula relating refunded dollars to promotional credit. Do not assume $1 refunded always removes $1 or $1.20 of credit. Before saving, require explicit cash and credit amounts. Warn when there has been prior spending or when bonus credit remains; the owner chooses the permitted outcome.

Validation:

- Cash refunds must be positive and must not exceed the original payment less earlier refunds.
- Credit removed cannot exceed the customer's available balance or the unspent credit associated with that payment's grant.
- Do not restore previously spent credit to make a refund possible without a separate documented correction.
- Multiple partial refunds must be tracked against the original payment.
- A fully refunded payment cannot receive another cash refund.
- Completed financial records cannot be overwritten or deleted. Correct a mistaken refund through a linked, owner-only compensating record with a reason, preserving the history of money actually returned.
- A credit adjustment by itself does not claim that cash was paid or refunded.

### Incorrect food order

Allow one complete reversal of a food transaction with a mandatory reason. Restore its deducted credit, retain the original receipt, and link the reversal to the original order. If the original grant was exhausted, it becomes usable again when the reversal restores a positive balance. A food reversal does not automatically return cash.

If necessary, save a replacement food order as a new transaction. Automatically send an approved correction notification showing the original reference, restored/removed credit, and updated balance. Payment refunds similarly send an approved refund confirmation showing cash refunded, credit removed, and remaining balance.

Only the owner can make manual credit adjustments. Require a reason, before/after balance preview, audit trail, and correction notification. Block negative balances.

## 8. Financial consistency

- Store USD amounts as integer cents: $200 = `20000`; $240 = `24000`.
- Use whole-number quantities initially and calculate all line totals on the server.
- Maintain an append-only credit ledger as the financial history.
- Available balance = credit grants + reversal credits + positive adjustments - food deductions - refund credit removals - negative adjustments.
- Keep cash received, cash refunded, bonus granted, food redeemed, and remaining credit distinct.
- Each payment creates an identifiable credit grant. Associate food deductions with the grant they consume; reversals restore the original allocation. This supports payment-specific refund checks.
- Store immutable snapshots of item names, prices, plan terms, and receipt balances.
- Use unique submission keys for payment, order, refund, reversal, and adjustment requests.
- Reusing a key with the same payload returns the original result; reusing it with a different payload is rejected.
- Serialize balance-changing operations, including enrollment and refunds, to prevent concurrent overspending or duplicate renewals.
- Mark grants active when credit remains, exhausted at zero, or closed after an owner-authorized full removal. None expire by date.
- Store business event time and software-entry time separately. Default orders to the current time; no backdated food spending in the first version.
- Archive customers without deleting their history. Require resolution of any remaining credit before archiving.

## 9. Automatic WhatsApp implementation

### Integration choice and one-time setup

Use the official WhatsApp Business Platform through **Twilio as the proposed provider**. Direct Meta Cloud API is an alternative; only one integration is needed. A `wa.me` link alone does not provide automatic sending.

1. Create a business-owned Twilio account.
2. Test using the WhatsApp Sandbox with designated recipients who join it.
3. Complete production WhatsApp sender onboarding with Ahaa Kitchen's business details and a controlled phone number.
4. Check current number eligibility and migration/coexistence rules before connecting a number already used in WhatsApp.
5. Submit payment/enrollment, food receipt, refund, and correction templates for approval.
6. Store provider credentials and approved template identifiers on the server.
7. Deploy the application, durable message worker, database, and HTTPS delivery callback endpoint.
8. Verify messages and failure handling before enabling real customer sends.

Customers only need WhatsApp, their registered number, and recorded notification permission. They do not need Twilio accounts.

After setup, daily operations take place in this website. Keep provider billing funded or active, and address occasional sender/template/account issues. Messaging carries ongoing charges; no fixed provider price or approval turnaround is promised.

Official implementation references: [Twilio WhatsApp overview](https://www.twilio.com/docs/whatsapp/api), [approved template sending](https://www.twilio.com/docs/whatsapp/tutorial/send-whatsapp-notification-messages-templates), and [WhatsApp quickstart](https://www.twilio.com/docs/whatsapp/quickstart). These references were checked during requirements preparation on October 30, 2026; recheck during integration.

### Templates and permission

Business-initiated messages outside the 24-hour customer service window require approved templates. Prepare templates for every automated event rather than depending on the customer recently sending a message. Final template wording, variable limits, and approval are controlled by the provider/Meta.

Preserve itemization. If a food list exceeds approved template limits, use a supported approved receipt document/media approach and retain full itemization in the application. Do not expose the private administration website as a public receipt link.

Record consent before sending. If permission is absent or withdrawn, save financial operations normally but skip messaging and show why. Provide an owner control to record opt-out requests and recheck permission before sending a queued message.

### Save-to-message flow

```text
Owner clicks Save Payment & Enroll / Save Order / Save Refund
                         |
Server validates owner access, amounts, and balance
                         |
One database transaction:
  financial record + ledger changes + immutable notification job
                         |
Commit succeeds -> show updated balance and Queued status
                         |
Background worker submits approved template through Twilio
                         |
Customer receives WhatsApp confirmation
                         |
Verified provider callback updates delivery status
```

Send only after a successful commit. Invalid forms, rejected orders, and failed saves must not generate customer confirmations. Closing the browser after a successful save must not cancel the queued message.

### Server endpoints

| Endpoint | Responsibility |
| --- | --- |
| `POST /api/enrollments` | Owner-only payment, credit grant, and confirmation job |
| `POST /api/orders` | Owner-only itemized deduction and receipt job |
| `GET /api/orders/:id` | Owner-only saved receipt and delivery status |
| `POST /api/orders/:id/reverse` | Owner-only reversal and correction job |
| `POST /api/refunds` | Owner-only refund, credit removal, and confirmation job |
| `POST /api/adjustments` | Owner-only reasoned credit adjustment and correction job |
| `POST /api/notifications/:id/retry` | Owner-only eligible message retry with no financial change |
| `POST /api/webhooks/twilio/status` | Signature-verified provider delivery callback |

### Server-only configuration

```dotenv
TWILIO_ACCOUNT_SID=<account identifier>
TWILIO_AUTH_TOKEN=<server secret>
TWILIO_WHATSAPP_FROM=whatsapp:+<approved business sender>
TWILIO_ENROLLMENT_CONTENT_SID=HX<approved payment template>
TWILIO_RECEIPT_CONTENT_SID=HX<approved food receipt template>
TWILIO_REFUND_CONTENT_SID=HX<approved refund template>
TWILIO_CORRECTION_CONTENT_SID=HX<approved correction template>
TWILIO_STATUS_CALLBACK_URL=https://subsription.ahaakitchen.com/api/webhooks/twilio/status
```

These are placeholders, not working credentials. Use the final selected hostname for callbacks. Never commit real secrets or expose them to the browser.

### Illustrative food receipt template

```text
Ahaa Kitchen receipt for {{1}}.
Order: {{2}}.
Food items: {{3}}.
Order total: {{4}} USD.
Remaining balance: {{5}} USD.
Collected at: {{6}}.
Validity: No expiry.
```

The variables contain customer name, order reference, approved compact item summary, order total, remaining balance, and collection date/time. There is no expiry variable. Payment templates include received amount, bonus, credit granted, balance, reference, and payment date. Refund/correction templates contain their respective amounts and original reference.

Illustrative Node.js worker submission using the Twilio SDK:

```js
import twilio from "twilio";

const client = twilio(
  process.env.TWILIO_ACCOUNT_SID,
  process.env.TWILIO_AUTH_TOKEN,
);

// Load an immutable committed receipt job, claim it, and check consent first.
async function submitFoodReceipt(receipt) {
  const message = await client.messages.create({
    from: process.env.TWILIO_WHATSAPP_FROM,
    to: `whatsapp:${receipt.phoneE164}`,
    contentSid: process.env.TWILIO_RECEIPT_CONTENT_SID,
    contentVariables: JSON.stringify({
      "1": receipt.customerName,
      "2": receipt.orderReference,
      "3": receipt.approvedItemSummary,
      "4": receipt.formattedOrderTotal,
      "5": receipt.formattedRemainingBalance,
      "6": receipt.formattedCollectedAt,
    }),
    statusCallback: process.env.TWILIO_STATUS_CALLBACK_URL,
  });

  // Persist this ID against the job; acceptance is not proof of delivery.
  return message.sid;
}
```

This snippet covers provider submission only. Production code must add durable job processing, validation, callbacks, retries, and the financial protections specified here.

### Delivery reliability

- Display queued, sent, delivered, read, failed, or skipped states according to provider support.
- Store the balance immediately after the event in the notification snapshot; later spending must not change an old receipt.
- Retry recoverable failures with bounded delays and expose permanent failures to the owner.
- Reconcile ambiguous provider timeouts before resending to reduce duplicates; do not promise exactly-once delivery.
- A failed message never reverses a valid payment, food deduction, or refund. A message retry never repeats the financial operation.
- Process queued events in customer order. Preserve references and event timestamps so delayed receipts are identifiable.
- Verify callback signatures, process repeated callbacks idempotently, and prevent older callbacks from regressing a delivered/read state.
- Reconcile callbacks arriving before the provider message ID has been persisted.
- Never silently redirect old queued receipts after a contact edit. Cancel unsent jobs where possible, verify the new number and permission, and create an audited replacement. Delivered messages cannot be recalled by the application.
- Immediate submission is the target; actual delivery depends on the provider and recipient connectivity.

## 10. Screens

| Screen | Features |
| --- | --- |
| Login | Owner authentication, logout, recovery, session expiry |
| Dashboard | Active customers, cash received/refunded, food redeemed, outstanding credit, exhausted accounts, failed messages |
| Customers | Search, registration, contact edits, archive |
| Customer profile | Unlimited-validity balance, Record Food, Renew Now at zero, payment/order/refund history |
| Payment/enrollment | Fixed offer, confirmed payment, credit preview, Save Payment & Enroll |
| Food entry | Item rows, tax-inclusive amounts, total, balance preview, Save Order |
| Refunds/adjustments | Owner-only amounts, reason, before/after preview, explicit confirmation, history |
| Notifications | Event, recipient, delivery state, error, controlled retry |
| Reports | Filtered cash/credit summaries, statements, CSV export |
| Settings | Owner account, fixed plan, restaurant details, integration status |

Design for quick phone use at the restaurant counter and a clear desktop layout. Keep customer search, available balance, and Record Food easy to access. No expiry warnings or monthly countdowns.

## 11. Ahaa Kitchen branding

Use the existing site's palette. The following values were found in the [homepage](https://ahaakitchen.com/) and [main stylesheet](https://ahaakitchen.com/assets/css/style.css?v=1005) during the October 30, 2026 review. Application roles below adapt those site colors to private administration screens.

| Color | Value | Application role |
| --- | --- | --- |
| Signature gold | `#E2C08D` | Main action backgrounds and highlights |
| Warm gold | `#D4A359` | Selected accents and borders |
| Deep gold | `#B89150` | Hover accents |
| Dark brown | `#332211` | Headings and text on gold buttons |
| Warm cream | `#FAF7F2` | Page background |
| Cream | `#F7F3E9` | Balance summaries and secondary panels |
| Pale beige | `#EBDCC5` | Dividers and borders |
| Soft beige | `#E8D9B5` | Muted highlights |
| White | `#FFFFFF` | Cards, inputs, tables |
| Near black | `#1A1A1A` | High-contrast text |
| Gray | `#666666` | Supporting text, subject to contrast checks |

The stylesheet also defines gold as `hsl(38, 61%, 73%)`, approximately `#E4C590`; consistently use the homepage's explicit `#E2C08D` for the application's primary token.

```css
:root {
  --ahaa-primary: #e2c08d;
  --ahaa-accent: #d4a359;
  --ahaa-accent-deep: #b89150;
  --ahaa-text: #332211;
  --ahaa-background: #faf7f2;
  --ahaa-panel: #f7f3e9;
  --ahaa-border: #ebdcc5;
  --ahaa-highlight: #e8d9b5;
  --ahaa-surface: #ffffff;
  --ahaa-text-strong: #1a1a1a;
  --ahaa-text-muted: #666666;
  --ahaa-font-heading: "Forum", Georgia, serif;
  --ahaa-font-body: "DM Sans", Arial, sans-serif;
}
```

Use the existing Ahaa Kitchen logo, Forum for brand headings, and DM Sans for forms, buttons, amounts, and tables. Keep cream backgrounds, white cards, gold actions, and dark brown text. Use readable dark text on gold buttons. Status labels must include words/icons rather than relying on color. Verify keyboard focus, contrast, and mobile usability.

## 12. Data model

| Entity | Important fields |
| --- | --- |
| Owner | ID, authentication identity, account status |
| Customer | ID, name, email, phone, WhatsApp number, consent history, notes, archive state |
| Plan | ID, name, payment cents, bonus cents, total credit cents, unlimited validity, active state |
| Payment | ID, customer, grant, amount cents, method, received time, entered time, external reference, submission key |
| Credit grant | ID, customer, payment, immutable plan snapshot, initial paid/bonus credit, remaining credit, active/exhausted/closed state |
| Food order | ID, customer, reference, total cents, balance before/after, event/saved time, submission key |
| Food item | ID, order, item name snapshot, quantity, tax-inclusive unit amount cents, line total cents |
| Allocation | Order/adjustment/refund/reversal linkage to original grant and credit amount |
| Refund | ID, original payment/grant, cash amount cents, credit removed cents, method, reason, external reference, event/saved time, owner, submission key |
| Credit ledger | ID, customer/grant, signed amount cents, type, linked financial event, reason, timestamp |
| Notification | ID, linked event, recipient/template/payload snapshot, state, provider message ID, attempts, last error |
| Audit event | ID, actor, action, affected record, timestamp, change details |

No grant expiry or renewal scheduling field is required. Enforce unique submission keys, valid relationships, and nonnegative balances in transactional operations. Preserve all prior plan terms when configuration changes. Reconcile any cached balance against the ledger.

## 13. Reports

- Cash received, cash refunded, and net cash by date/customer/method.
- Paid credit and promotional bonus granted separately.
- Food credit redeemed with item detail.
- Current outstanding credit with no expiry exclusion.
- Refund credit removals, order reversals, and manual adjustments.
- Customer statements with opening balance, all movements, and closing balance.
- Exhausted accounts eligible for immediate renewal.
- Failed or stuck notifications.
- CSV export matching the screen's filters.

Do not report $240 granted credit as $240 cash received. These are operational reports; accounting treatment is separate.

## 14. Security and operations

- Enforce owner authorization on every private server endpoint and database operation. Provider callbacks use signature verification instead of owner login.
- Use established authentication, secure sessions, password recovery, and multi-factor authentication where supported.
- Keep credentials and customer details out of public code, browser bundles, and routine logs.
- Use HTTPS, validation, login throttling, and appropriate request protections.
- Store timestamps in UTC; display restaurant events in `America/Chicago` with daylight saving handling.
- Require internet access to save. After a timeout, check the original request result and reuse its submission key; do not assume an offline action saved.
- Run durable workers and monitor failed/stuck message jobs and integration problems.
- Back up the database automatically and verify restoration.
- Keep audit history of payments, grants, food orders, refunds, reversals, adjustments, contact changes, and notification retries.
- Separate development/test recipients and configuration from production. Sandbox testing does not establish production readiness.
- Restrict exports and decide retention/deletion procedures before production.

## 15. Implementation stages

No application stack or hosting provider has been selected. The system requires a responsive web UI, authenticated server/API, transactional relational database, durable notification worker, and HTTPS callback handling.

1. Confirm final hostname, early top-up scope, and the manual refund procedure.
2. Implement owner authentication and Ahaa Kitchen design tokens.
3. Implement customers, consent, and search.
4. Implement the $200/$240 credit grant, ledger, and zero-balance renewal.
5. Implement tax-inclusive food entry, balance validation, and order history.
6. Implement owner-only refunds, reversals, and adjustments.
7. Connect approved WhatsApp templates, delivery callbacks, retries, and permission checks.
8. Add reports, exports, backups, and monitoring.
9. Verify the end-to-end flows and deploy to the selected subdomain.

## 16. Acceptance criteria

- [ ] Only the owner can access customer/financial screens or change credit.
- [ ] Customer registration captures name, email, phone, WhatsApp number, and consent.
- [ ] A confirmed $200 payment grants exactly $240 and automatically queues a payment WhatsApp confirmation.
- [ ] Payment and refund screens only record external transactions; no Razorpay or other payment gateway, checkout, payment webhook, or money-moving API exists.
- [ ] Partial/mismatched payments cannot activate the fixed offer.
- [ ] Credit remains available indefinitely; there is no automatic expiry or monthly reset.
- [ ] A $40 order reduces $240 to $200 and automatically sends the itemized receipt without a separate send action.
- [ ] Entered bill values include tax, and the system adds no separate tax.
- [ ] An order equal to available credit succeeds and leaves zero.
- [ ] An oversized order shows Not sufficient balance and creates no deduction or receipt job.
- [ ] At zero balance, another $200 payment immediately grants a fresh $240.
- [ ] Retries/double taps do not duplicate payments, credit, orders, refunds, or message jobs.
- [ ] Concurrent financial operations cannot overspend or duplicate a renewal.
- [ ] Only the owner can record refunds and choose the explicit permitted cash/credit amounts.
- [ ] Refund totals cannot exceed original cash received less prior refunds, and credit removals cannot produce a negative balance.
- [ ] Refund corrections retain immutable financial history and do not claim money moved unless recorded as such.
- [ ] One complete food reversal restores the original credit allocation and queues a correction notice.
- [ ] Message failure leaves committed finances unchanged; retry only resubmits the notification.
- [ ] Delivery callbacks update state safely and invalid signatures are rejected.
- [ ] No automated message is sent without notification permission.
- [ ] Reports reconcile cash, bonus, deductions, refunds, and outstanding balances.
- [ ] The interface uses Ahaa Kitchen branding and works on phone and desktop.
- [ ] A database backup can be restored successfully.

## 17. Remaining decisions

The main business rules above are confirmed. These details remain open:

1. **Hostname:** preserve `subsription` or use corrected `subscription`?
2. **Top-up before zero:** can the customer pay another $200 while some credit remains? The initial scope only guarantees renewal after exhaustion.
3. **Refund practice:** the owner controls refunds, but must choose cash returned and credit removed explicitly; no automatic bonus/refund formula has been agreed.

## 18. Outside the initial scope

- Customer login, self-service ordering, or public subscription checkout.
- Automatic payment collection, stored cards, recurring charges, or bank deposit detection.
- Razorpay, Stripe, PayPal, or any other payment gateway integration, including payment links and payment/refund webhooks.
- Split-payment food orders or negative balances.
- Automatic tax calculations or separate tax charging.
- Automatic expiry, monthly resets, or scheduled renewal periods.
- Inventory, delivery scheduling, full POS replacement, multiple branches, or staff roles.
- Promotional campaigns, automatic email/SMS, credit sharing, or transfers between customers.
