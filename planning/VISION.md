# QP-CRM — the big idea, in plain language

*For everyone who will use the system, not just for programmers. The technical version
lives in `INTEGRATION_TECHNICAL.md`; unanswered decisions live in `OPEN_QUESTIONS.md`.*

---

## Why we're doing this

Today the same information lives in many places: offers and invoices in Word/Excel, an old
CRM, a ticketing program for service, an accounting stock program, and an Excel table that
tracks what's on stock, ordered, and reserved — and for whom. None of it talks to each
other, so every answer ("what did we sell that customer? where is that lift? is Subotica
paid?") means opening three programs.

The idea: **one app, one thread per job, everything attached to that thread.** We already
have a good base — the pricing and offers part of this app works, prints beautiful PDFs,
and knows our products. We build the rest around it.

## The one rule that keeps it from becoming a mess

Every new feature must be one of three things:

1. a **document** on a job (offer, invoice, travel order, work order…),
2. a **view** over things already stored (lists, overviews, reminders),
3. **master data** (a customer, a product, a machine, a van).

Anything else — a new separate workflow, a second place to enter the same customer, a new
status nobody maintains — does not get built. This is the promise that keeps the app
clean in year five, not just year one.

## The spine: one deal per request

Every job — a sale, a service call, a big project — is one **deal**. Like a case file:

```
DEAL  "ABC Transport — 2-post lift + PTI lane"
 ├─ the story: phone call note, emails, meeting notes — in order, with dates
 ├─ OFFER 1 (not accepted) → OFFER 2 (accepted)
 ├─ INVOICE → payments (who paid, when, how much)
 ├─ what we reserved in stock for this deal, what we ordered for it
 ├─ TRAVEL ORDER → WORK/SERVICE ORDER (the paper the customer signs)
 └─ status that tells itself: not chosen by hand
```

The deal has its own code (like **D-2026-014**) that we write in emails and documents, so
nobody ever wonders which job something belongs to — even when a customer has three jobs
running at once.

## Statuses tell themselves

Nobody fills in "status" dropdowns. The app looks at what exists:

- an offer exists → deal is "offered"
- an invoice was issued → deal is "won"
- payments cover the invoice → "paid"
- the signed work order is attached → "done"

Because nobody maintains them, they can never lie. The pipeline screen ("what's in the
air at every customer right now") is always true.

## Customers can have many workshops and many jobs at once

- **Customer** = the company (the name and PIB that goes on the invoice — who pays).
- **Location** = their workshop or site (where the work actually happens). A customer can
  have five. If a job is at the headquarters, no location is needed.
- **Deal** = one job. A customer can have several at the same time, each with its own
  story, its own documents, its own reserved stock, its own status.

The customer page shows all live jobs side by side. There is no single "status of the
customer" — that would be a lie when two jobs run in parallel.

Two promises that make parallel jobs safe:
- stock shows what's reserved **and for whom** across ALL jobs, so two deals can't
  silently promise the same machine;
- a payment is attached to a specific invoice — never a fuzzy "customer account".

## Machines are remembered — forever

Anything with a serial number (a lift, a tester, a PTI lane) gets one record that lives
forever. The record always knows **where the machine is and since when**:

> Lift SN 88231 — at ABC Transport, Subotica, since 14.03.2026.

The record is never deleted. Even a scrapped lift keeps its row — it just says "scrapped".
So if we bought 10 lifts in 2024, there will always be 10 rows, and a lift can never
silently disappear from the books of the app. When a customer's own machine comes to us
for service, it gets a row too — so nothing standing on our floor is unknown.

Because of that, later (service phase) every machine automatically has its history: when
we sold it, what we fixed, which part came from where — and it can remind us when its
maintenance is due.

## The warehouse: simple on purpose

Three kinds of things, three levels of effort:

| | Example | What we do |
|---|---|---|
| **Machines (serial numbers)** | lifts, testers | Register once, then tap when they move. Strict — always true. |
| **Things worth counting** (only if we choose) | oil drums, expensive spares | Loose numbers: boxes, liters. Fixed twice a year at a stocktake. |
| **Small parts** | screws, clamps | **Not tracked at all.** They exist so offers and orders can name them. That's all. |

Nobody will ever count screws. If some part class ever becomes important, we switch it on
with one setting — nothing needs rebuilding.

**"What is reserved and for whom, what's coming"** — one screen:
what's physically here, what's promised to which job, what's ordered from suppliers and
when it lands. That screen is also the "what do we need to order" list. Ordering itself
stays human — the screen shows the gap, a person creates the purchase order.

**Free, loaned, test machines are normal.** Moving a machine to a customer never requires
an invoice. Every movement says *why* (sold / given free / loaned / for test / returned /
repair…) and *optionally* which document it belongs to. The question "what do we have at
that customer, and since when?" is answered without any invoice existing.

**Our vans are mini-warehouses.** A van is not a customer (so customer lists and reminders
stay clean). "Mechanic took parts Monday" is one movement into the van; unused parts go
back; a part used at a customer is one tap. The van page shows what's inside it right now
and where everything went.

**When we sacrifice parts (cannibalize):** taking a part off lift A to fix lift B creates
a small **debt note**: "lift A is missing a hydraulic hose, taken for job D-2026-014".
Lift A shows a red flag on its page, the missing part appears on the orders-needed list,
and when the replacement purchase order arrives, the debt closes itself. Two taps. A plain
note would also be possible — but notes forget; debts get remembered.

**This app is not the audit warehouse program.** The counting program (in-and-sold, for
the books) stays what it is. This app knows *where machines are* and *what owes what to
whom* — it deliberately does not try to value inventory. That division is why both stay
simple.

## Product names never break

- Every list row keeps its own copy of the name as written (a "temp product" in an offer
  or warehouse entry needs no catalog entry — and one click can turn it into a real
  product later).
- Renaming a product or customer = edit one place. Everything shows the new name.
  Nothing breaks.
- Duplicates (five versions of the same product) can be merged into one. The old numbers
  keep working invisibly, so old offers and movements stay intact.
- Old, already-sent offers always show the names as they were written that day — history
  is not rewritten.

## What we deliberately do NOT put in

- **Accounting / books** — the finance software stays the legal truth for receipts and
  ePayments. The app makes the invoice PDF and tracks payments; the accountant does the rest.
- **Counting inventory value** — the audit warehouse program stays.
- **Typical CRM bloat** — campaigns, lead scoring, portals, custom-field builders.
- **Importing all the old CRM/ticketing history** — fresh start; only customers come over
  (and even that is your decision — see OPEN_QUESTIONS.md).

## The road, in order

1. **Deals spine** — customers, locations, deals, the story, link to offers; then invoice
   + payments. *Replaces the old CRM and the "nothing is linked" problem.*
2. **Warehouse & machines** — movements, serials, reservations, purchase orders, vans,
   donor-part debts. *Replaces the Excel.*
3. **Service documents** — travel orders, work orders, service reports on the same deal;
   machine histories. *Replaces the ticketing program.*
4. **Field work** — phone-friendly pages, customer signs on the device, maintenance
   reminders. *Replaces paper in the field.* (Needs HTTPS first — already on the board.)

Each phase counts as done only when the old tool it replaces is actually switched off.

## Why this one won't rot like other CRMs

- One thread per job — everything is attached somewhere you can find.
- Statuses are computed, never typed.
- Machines, customers, products each have ONE home; everything else is a link.
- Every addition must prove it is a document, a view, or master data.
- Small parts stay untracked; the app stays fast and honest about what it knows.

And a bonus: because every document is linked to its deal from birth, the questions you
currently answer by opening five programs — what did we sell them, what discount did we
give on accepted deals, which items sell best, how much is at each customer — become
simple filters and reports on live data.
