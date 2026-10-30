# Ahaa Kitchen Subscription Management

Detailed product requirements for a private, owner-operated food credit management system for [Ahaa Kitchen](https://ahaakitchen.com/).

**Project status:** Requirements only. This README does not represent a built application, configured subdomain, payment integration, or connected WhatsApp account.

## 1. Purpose

Ahaa Kitchen customers pay in advance and receive a food credit balance. The owner registers each customer, records the payment, enrolls them in a monthly plan, and records food collected throughout the month. Every saved food transaction reduces the customer's available balance and immediately queues a WhatsApp receipt showing the food items, order total, and remaining balance.

The application is for the owner only. Customers receive WhatsApp updates but do not need accounts or access to the software.

### Main example

| Event | Amount |
| --- | ---: |
| Customer pays Ahaa Kitchen | $200.00 |
| Promotional bonus credit | $40.00 |
| Total food credit granted | $240.00 |
| Customer collects food worth | $40.00 |
| Remaining food credit | $200.00 |

All amounts are **US dollars (USD)**. The $240 credit is spending value, not an additional payment or cash received. The initial offer gives 20% extra food credit on the $200 payment.

## 2. Access and subdomain

- Requested address: `https://subsription.ahaakitchen.com`.
- The requested spelling is preserved here. The conventional spelling would be `https://subscription.ahaakitchen.com`; choose the final address before configuring DNS.
- Separate private application under the existing Ahaa Kitchen domain.
- Login required before viewing any customer, financial, or reporting page.
- One owner account initially, with public registration disabled.
- Customers cannot sign up, log in, change balances, or submit orders through this application.
- Configure the subdomain and HTTPS only when the application is ready for deployment.
- Use `noindex` for the private application, while enforcing access through server-side authentication. Hiding a URL is not access control.

## 3. Requirements versus proposed defaults

### Confirmed requirements

1. The owner creates customers with their name, email, and phone number.
2. The owner records a $200 payment and grants $240 food credit.
3. Customers can use their credit for multiple food collections during the month.
4. The owner enters food item names and amounts for each collection.
5. The system deducts the order total and tracks the remaining balance.
6. The system automatically sends a WhatsApp transaction notification.
7. The application uses the existing ahaakitchen.com color palette.
8. Only the owner uses the application.

### Proposed defaults to confirm before implementation

| Topic | Proposed behavior |
| --- | --- |
| Monthly validity | One calendar month from the selected start date, rather than a fixed 30 days |
| End boundary | Start is inclusive; the displayed expiry timestamp is exclusive |
| Month-end dates | Clamp to the last valid date of the following month, retaining the start time |
| Example | October 30 at 10 AM to November 30 at 10 AM, restaurant local time |
| Unused credit | No automatic rollover; unused credit expires at the period end |
| Renewal | Manual enrollment after recording a new payment; no automatic card charge |
| Active subscriptions | One active enrollment per customer |
| Early renewal | Schedule the next period after the current period ends; do not overwrite the current balance |
| Insufficient balance | Block the transaction; no negative balance or split payment in the first version |
| Tax and discounts | Owner enters the final amount to deduct; confirm tax treatment before implementing automatic calculations |
| Refunds | Owner-reviewed manual procedure; the system records any resulting adjustment and payment refund separately |
| Business timezone | `America/Chicago`, matching the Frisco restaurant, including daylight saving changes |

These defaults are planning assumptions, not confirmed customer terms. Final expiry, rollover, refund, and tax rules must be settled before selling the plan.

## 4. Owner workflow

### Step 1: Create a customer

Enter:

- Full name, required.
- Email address, required for the initial specification.
- Phone number with country code, required; example: `+19453575262`.
- WhatsApp number, defaulting to the phone number, with an option to use a different number.
- WhatsApp notification permission, including when and how the customer agreed.
- Optional internal notes.

Validate email and international phone formatting. Warn about matching phone numbers and emails before creating duplicate records. If customers share a family number, allow an explicit owner override with a reason and keep their balances separate.

### Step 2: Record payment and enroll

1. Select the customer.
2. Select the plan: **Pay $200 / Get $240 Food Credit**.
3. Record the actual payment amount, date, payment method, and optional reference.
4. Select the subscription start date and review the calculated expiry.
5. Review the $200 paid, $40 bonus, and $240 total credit separately.
6. Save the payment, enrollment, initial ledger credit, and notification job together.
7. Queue an enrollment WhatsApp notification if the customer has agreed to notifications.

The owner records money received externally, such as cash, a card terminal payment, or a transfer. Online payment collection and recurring billing are outside the initial scope. Recording a payment does not itself charge the customer.

### Step 3: Record food collection

1. Find the customer by name, email, phone number, or customer ID.
2. Open the active subscription and see its available balance and expiry.
3. Add food item names, quantities, and unit prices.
4. Review the final order amount and resulting balance.
5. Select **Save & Send WhatsApp**.
6. Save the transaction, deduct the balance, and queue the receipt as one database transaction.
7. Show the saved receipt and WhatsApp delivery status.

Example:

| Food item | Quantity | Unit price | Line total |
| --- | ---: | ---: | ---: |
| Chicken Biryani | 1 | $18.00 | $18.00 |
| Paneer Curry | 1 | $14.00 | $14.00 |
| Naan | 2 | $4.00 | $8.00 |
| **Total credit used** | | | **$40.00** |

Before: **$240.00**. Deduction: **$40.00**. Remaining: **$200.00**.

Allow repeat collections on the same day while the subscription is valid and sufficient credit remains. Use manually entered items initially; a reusable item catalog can be added later.

### Step 4: View history and renew

The customer profile shows contact details, current enrollment, payment history, food collections, ledger entries, receipt details, notification status, and previous subscriptions. Renewal creates a new enrollment and preserves all previous records.

## 5. Screens

| Screen | Required features |
| --- | --- |
| Owner login | Secure login, logout, password recovery, session expiry |
| Dashboard | Active subscriptions, cash received in selected period, food credit redeemed, outstanding valid credit, expiring subscriptions, failed messages |
| Customers | Search, add customer, edit contact information, archive customer |
| Customer profile | Balance, validity, enroll/renew action, record-food action, history and message status |
| Enrollment form | Plan, payment details, start/expiry, bonus and total credit preview |
| Record food | Item rows, quantities, prices, total, balance before/after, save action |
| Transactions | Filters by customer/date/status, receipt view, reversal action with reason |
| Notifications | Queued/sent/delivered/read/failed states when supported, error details, controlled retry |
| Reports | Payment totals, credit granted, redemption, expiry, balances, CSV export |
| Settings | Plan configuration, restaurant details, owner account, notification integration status |

Design for fast use on a phone at the restaurant counter, with a clear desktop layout as well. Keep customer search and the **Record Food** action easy to reach.

## 6. Balance and transaction rules

- Store amounts as integer cents: $200 = `20000`, $240 = `24000`, and $40 = `4000`.
- Use a permanent ledger to explain every change in credit.
- Available balance = granted credit + permitted positive adjustments + valid reversal credits - food deductions - negative adjustments - expired credit.
- Cash paid, bonus granted, food redeemed, and expired credit must remain separate reporting values.
- Validate all calculations on the server; never trust a balance supplied by the browser.
- Require positive quantities and nonnegative prices, with a positive final order total.
- Do not allow spending from an expired, cancelled, scheduled, or exhausted enrollment.
- An order equal to the balance is valid and leaves $0.00; mark the enrollment exhausted.
- Reject an order larger than the available balance with a clear message.
- Prevent duplicate deductions from double taps, retries, or a refreshed form using a unique submission key.
- Lock or otherwise serialize balance updates so two simultaneous saves cannot overspend the account.
- After saving, do not silently edit or delete financial transactions. Correct an error through a linked reversal and, if needed, a replacement order.
- Require a reason for reversals and manual adjustments, retaining the owner and timestamp.
- Permit only one complete reversal per food transaction in the initial version.
- A reversal restores spendable credit only while its original enrollment is still valid. After expiry, preserve the correction in the ledger without reopening expired credit; any replacement credit requires a separate explicit owner adjustment under the agreed policy.
- Customer contact edits must not rewrite the destination and content already recorded for past receipts.
- Archiving a customer keeps their financial history intact. Block archiving while usable credit remains until the owner resolves it.

### Expiry handling

Enforce validity whenever an order is saved, even if a scheduled expiry job has not run. A background job records unused credit expiration exactly once and updates enrollment status. Reports must exclude expired credit from usable balances even before the job catches up.

## 7. Automatic WhatsApp notifications

### Required behavior

Use an official WhatsApp Business Platform integration, directly or through a provider such as Twilio. A `wa.me` link only opens a chat and does not satisfy automatic sending.

The receipt must contain:

- Ahaa Kitchen name and customer name.
- Unique order reference and transaction date.
- Food names, quantities, and line totals.
- Total amount deducted in USD.
- Remaining balance immediately after this transaction.
- Subscription expiry.

Proposed receipt copy:

```text
Ahaa Kitchen
Hi Ravi, your food collection has been recorded.

Order: AK-000123
Chicken Biryani x1 - $18.00
Paneer Curry x1 - $14.00
Naan x2 - $8.00

Total deducted: $40.00 USD
Remaining balance: $200.00 USD
Valid until: Nov 30, 2026, 10:00 AM CST

Thank you for choosing Ahaa Kitchen!
```

Proposed enrollment copy:

```text
Ahaa Kitchen
Hi Ravi, your monthly food credit plan is active.

Payment received: $200.00 USD
Bonus credit: $40.00 USD
Total food credit: $240.00 USD
Valid until: Nov 30, 2026, 10:00 AM CST

Collect food during your plan period and we will update your balance after each order.
```

These are draft message contents. Their final structure and variable limits must match an approved provider template. Preserve itemization; if an item list exceeds the selected template's limits, use an approved receipt document/media approach and retain the full itemized receipt in the application.

### Setup dependencies

- Business-owned WhatsApp sender onboarding and production access.
- Provider credentials stored on the server.
- Customer opt-in records and a way to stop future notifications when requested.
- Approved templates for business-initiated notifications outside the customer service window.
- A public HTTPS callback endpoint to receive delivery updates, with provider signature verification.
- Provider messaging charges, limits, and template approval to be checked during implementation.

WhatsApp's customer service window lasts 24 hours after the customer's most recent message; outside it, an approved template is required. See [Twilio's official WhatsApp overview](https://www.twilio.com/docs/whatsapp/api) and [template notification documentation](https://www.twilio.com/docs/whatsapp/tutorial/send-whatsapp-notification-messages-templates). Requirements were checked on October 30, 2026 and should be rechecked when integrating.

### Reliability

1. Commit the food transaction and an outbound notification record in the same database transaction.
2. A background worker submits the receipt immediately after commit.
3. Display **Queued**, **Sent**, **Delivered**, **Read**, or **Failed**, according to provider support. Sent does not mean delivered.
4. Store the original transaction's balance snapshot; do not substitute a newer balance during retry.
5. Retry recoverable failures with bounded delays. Reconcile ambiguous provider timeouts before resending to reduce duplicate receipts.
6. Display permanent failures and allow an owner-triggered retry after correcting the problem.
7. Use unique message jobs and idempotent callback processing. Do not claim exactly-once delivery when the provider cannot guarantee it.

A failed WhatsApp message must not undo a correctly saved food deduction. Retrying a message must never deduct the food amount again. Immediate submission is the goal; actual delivery depends on the provider and recipient connectivity.

If the customer has not agreed to messages or withdraws permission, save food transactions normally, skip WhatsApp delivery, and clearly show the reason.

## 8. Ahaa Kitchen branding and color palette

Use only the existing site's palette for the interface. The values below were found in the public homepage and its stylesheet on October 30, 2026. The roles assigned here adapt those existing colors to an administration interface.

Sources: [Ahaa Kitchen homepage](https://ahaakitchen.com/) and [main stylesheet](https://ahaakitchen.com/assets/css/style.css?v=1005).

| Existing site color | Value | Proposed application use |
| --- | --- | --- |
| Signature gold | `#E2C08D` | Main action backgrounds, highlights, active navigation |
| Warm gold | `#D4A359` | Secondary accents, selected borders |
| Deep gold | `#B89150` | Hover accents and decorative emphasis |
| Dark brown | `#332211` | Main text, headings, text on gold buttons |
| Warm cream | `#FAF7F2` | Page background |
| Cream | `#F7F3E9` | Alternate panels and balance summaries |
| Pale beige | `#EBDCC5` | Borders and dividers |
| Soft beige | `#E8D9B5` | Muted highlights |
| White | `#FFFFFF` | Cards, form inputs, table surfaces |
| Near black | `#1A1A1A` | High-contrast text |
| Gray | `#666666` | Supporting labels, subject to contrast checks |

The main stylesheet also defines signature gold as `hsl(38, 61%, 73%)`, which rounds to `#E4C590`; the homepage explicitly uses `#E2C08D`. Use the homepage's `#E2C08D` consistently for the application primary token.

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

### Visual direction

- Use the existing Ahaa Kitchen logo, with an approved asset supplied or copied from the owner's site during implementation.
- Use **Forum** for brand headings and **DM Sans** for forms, tables, buttons, and amounts, matching the existing website fonts.
- Keep the application light, with cream backgrounds, white cards, gold actions, and dark brown text.
- Display available balance prominently on customer profiles and the food entry screen.
- Use dark text on light gold buttons; avoid small gold text on white where contrast is insufficient.
- Label all status states in words and use distinct icons so meaning does not rely on color.
- Keep focus states visible and verify contrast, keyboard access, and mobile input usability.
- Avoid introducing an unrelated dashboard color theme.

## 9. Proposed data model

| Entity | Important fields |
| --- | --- |
| Owner | ID, email, authentication identity, account status, created timestamp |
| Customer | ID, name, email, phone, WhatsApp number, consent state/source/time, notes, archived timestamp |
| Plan | ID, name, payment amount cents, bonus cents, total credit cents, validity policy, active state |
| Enrollment | ID, customer, plan, immutable plan terms snapshot, start/end, status |
| Payment | ID, customer, enrollment, amount cents, currency, method, received date, reference, recorded by |
| Food transaction | ID, customer, enrollment, reference, total cents, balance before/after, occurred/saved timestamps, submission key, reversal linkage |
| Food item | ID, transaction, item name snapshot, quantity, unit price cents, line total cents |
| Credit ledger | ID, enrollment, entry type, signed amount cents, linked transaction/payment, reason, owner, timestamp |
| Notification | ID, customer, event/transaction, destination snapshot, template/payload snapshot, state, provider message ID, attempts, last error |
| Audit event | ID, actor, action, affected record, timestamp, relevant change details |

Enforce relationships and uniqueness in the database. Preserve old plan terms when pricing changes. Maintain a reconciled balance projection if needed for performance, while keeping the ledger as the source of financial history.

## 10. Reports

- Actual payments received by day, month, method, and customer.
- Food credit granted, separating paid value and promotional bonus.
- Food credit redeemed by date and customer, with item details.
- Valid outstanding balances and subscriptions approaching expiry.
- Expired unused credit and manual adjustments.
- Customer statements showing opening balance, credits, deductions, adjustments, and closing balance.
- Notification failures requiring attention.
- CSV export with filters matching the displayed report.

Do not label $240 granted credit as $240 cash revenue when only $200 was received. These are operational reports; accounting treatment is separate from the application's credit calculations.

## 11. Security and operations

- Enforce owner authorization on every server route and database operation.
- Use established authentication with securely managed sessions and password recovery; enable multi-factor authentication where supported.
- Keep customer data and notification credentials out of browser bundles, public repositories, and routine logs.
- Use HTTPS, server validation, login throttling, and appropriate request protections.
- Store timestamps in UTC and display business dates in `America/Chicago`.
- Back up the database automatically and verify that a backup can be restored.
- Keep an audit trail for payment entries, contact changes, enrollments, reversals, adjustments, and messaging retries.
- Use separate development and production credentials and test recipients.
- Restrict exports to the owner and protect customer contact information.
- Decide retention and deletion procedures before production; preserve required financial history while handling customer data requests deliberately.

## 12. Implementation outline

No technology stack has been selected yet. The system needs:

1. A responsive web interface with authenticated owner access.
2. A server/API for payment recording, enrollments, ledger updates, and reporting.
3. A transactional relational database for balances and history.
4. A durable outbound message queue or transactional outbox and background worker.
5. Scheduled expiry processing and delivery callback handling.
6. Hosting with HTTPS, environment secrets, backups, and support for the chosen subdomain.

The marketing website can remain independently hosted. Select the application stack after reviewing the available hosting and WhatsApp account setup.

### Suggested build order

1. Confirm period/expiry rules, refund handling, final subdomain spelling, and payment amount treatment.
2. Build owner authentication and apply the verified Ahaa Kitchen visual tokens.
3. Build customer registration and search.
4. Build payment recording, enrollment, and the ledger.
5. Build food entry, balance checks, transaction history, and reversals.
6. Integrate WhatsApp templates, durable sending, callbacks, and failure handling.
7. Add expiry processing, reports, exports, and backups.
8. Validate the complete owner workflow and configure the production subdomain.

## 13. Acceptance criteria

- [ ] An unauthenticated visitor cannot read customer details or change balances.
- [ ] The owner can create a customer with name, email, phone, and recorded WhatsApp permission.
- [ ] Recording a $200 payment grants exactly $240 credit under the initial plan.
- [ ] A $40 itemized transaction changes $240 to $200 and preserves the receipt.
- [ ] Another $25 transaction changes $200 to $175 with a separate history entry.
- [ ] An order equal to the remaining balance succeeds and leaves zero.
- [ ] An order larger than the balance fails without saving any deduction.
- [ ] A double tap or retried request creates only one food transaction and deduction.
- [ ] Simultaneous saves cannot produce a negative balance.
- [ ] Expired subscriptions cannot be used even if the expiry job is delayed.
- [ ] An erroneous transaction can be reversed once with a reason and a visible audit trail.
- [ ] A successful save immediately queues the itemized WhatsApp receipt with the correct balance snapshot.
- [ ] Message failure is visible, and retry does not create another deduction.
- [ ] Customers without notification permission do not receive automated messages.
- [ ] Renewal preserves all earlier payments, enrollments, and food history.
- [ ] Reports separate $200 cash received from $240 granted food credit.
- [ ] The interface uses the Ahaa Kitchen palette and works on phone and desktop.
- [ ] A production backup can be restored successfully.

## 14. Outside the initial version

- Customer login or self-service ordering.
- Online checkout, stored cards, automatic monthly charges, or payment gateway integration.
- Public subscription sales pages.
- Delivery scheduling, kitchen inventory, or full POS replacement.
- Multi-branch operation or staff permissions.
- Automatic email/SMS notifications or promotional campaigns.
- Credit sharing, transfers between customers, split tenders, and automatic rollover.

These can be added later if needed. The first version focuses on owner-managed customers, prepaid food credit, accurate deductions, and automatic WhatsApp receipts.
