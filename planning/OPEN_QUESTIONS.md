# QP-CRM — open questions & ideas for you

*Everything below is deliberately NOT decided yet. None of it blocks building Phase 1
(the deals spine) — most decisions can wait until the phase that needs them. Answer in any
order; the ones marked ⏰ matter soonest.*

---

## A. Decisions that shape the next build

**1. ⏰ Seed customers from the old documents? (yes/no)**
You chose a fresh start — but your `MH fin analitike` work already extracted ~4,650
normalized companies (name, PIB, MB, address, phone/email where captured) from 9,000 old
documents. We can load them once into the new customer list so nobody types by hand.
Recommended: yes, with PIB/MB dedupe; rows without PIB get flagged for review.
Cost of skipping: weeks of typing and the first months of "new customer or old one?"
confusion. Cost of accepting: a few duplicate-looking entries to clean (the merge tool
makes that painless).

**2. ⏰ What happens to the rent module's separate client list?**
QP-CRM already has `rent_clients` (PIB/MB, bank accounts, guarantors). The new universal
customer list will be separate at first. Later we must either (a) merge rent clients into
the universal list (cleaner, one customer = one row everywhere — recommended), or
(b) keep two lists linked. Decide before rent users start working daily in the new system,
not after.

**3. Phase names/numbers.** The old repo history used P0–P3; the new plan continues with
P4–P7 (deals, warehouse, service docs, field). Fine as is — or rename the new ones
(e.g. DEALS-1, WH-1…) if the old numbering annoys anyone. Cosmetic.

**4. Invoice numbering rules.** App-issued invoices will be numbered globally per year
(like today). Confirm: own sequence per year, no restart per customer, no per-deal
sequences — and confirm the number format your accountant wants on the PDF
(e.g. `2026/0142` vs `INV-2026-0142`).

**5. Do invoices need a fiscal/device or eFaktura connection?** You said receipts and
ePayments come from the finance software, so we assumed plain PDF invoices are enough.
If your accountant says invoices must enter eFaktura (Serbia) or a fiscal device, that's
a separate mini-project — tell us early, it affects the invoice phase.

---

## B. Workflow details to pin down while building

**6. Who is allowed to do what?** Today: admins everything; staff get module checkboxes.
New question: can a technician see deals and machines but not margins/prices? Can an
office person issue invoices but not edit products? Sketch your roles (boss, office
sales, service dispatcher, field tech, warehouse) and we'll map them to grants.

**7. The "call log" discipline.** The system only works if the first call is logged.
Agreed target: creating a deal takes under 30 seconds (pick customer, type one line, done).
Anything more and people stop doing it. When we build it, test that limit with the person
who answers the hotline — and tell us if it fails the 30-second test.

**8. Deal codes in emails (D-YYYY-NNN) — yes?** Every deal gets a code that appears on
documents and that staff write in emails/notes. Confirm you want that visible to
customers on PDFs, or internal-only.

**9. Offer acceptance: one tap or automatic?** Two options: (a) a staff member taps
"customer accepted offer #2" (a recorded decision — recommended, mirrors reality), or
(b) acceptance is implied when an invoice is issued. We recommend (a) + (b) combined.
Your old tickets had "accepted" states nobody trusted — this is why we derive, but the
acceptance tap is honest human knowledge worth recording.

**10. Multi-currency deals.** Offers already fetch NBS rates. For invoices: is RSD the
only invoice currency, or do you invoice in EUR for some customers (and which rate/date
rules — NBS middle, contracted rate)? Affects the invoice builder.

**11. Payment allocations in practice.** Model: one payment can cover several invoices by
amount. Who records payments — office only, or should the person who sees the bank alert
do it? And do you want an "unallocated payment" inbox for transfers without a reference?

**12. Purchase orders: how much detail?** Minimum: supplier name, lines, expected arrival,
status (ordered/partially/received). Optional extras: supplier as a full partner row with
contacts and price history; supplier invoices/quotes attached as PDFs. Tell us how you
work with suppliers today and we'll size it.

**13. Van consumption at customers: required or best-effort?** One tap per part used at a
customer (from the van). If mechanics won't do it even at one tap, van pages drift from
reality. Decide: is van accountability a rule (checked weekly) or a nice-to-have? The
mobile flow will make it as easy as possible either way.

**14. Donor-part debts: who may close one?** Auto-close happens when the replacement PO
is received. But sometimes the debt is settled differently (found the part, customer
brought one, decided to leave it). Who can close a shortfall by hand, and does it need a
reason note? (Recommended: dispatcher or boss only, note mandatory.)

**15. Serial numbers: how do they arrive?** Do supplier deliveries come with serial lists
(e.g. on the delivery note/Excel), or do you read plates one by one when registering?
If suppliers send lists, we should build "paste a list of serials → creates N instances"
— a big time-saver worth knowing early.

**16. What did the OLD ticketing software do that we must not lose?** Fresh start was the
decision — but name any 2–3 concrete features your team actually uses there (e.g. the
techs' weekly schedule? photos on the work order? the printed daily plan?). We'll make
sure each has a home in the deals/service design before we switch you off the old system.

**17. Document archive policy.** Everything is kept by default (no deletes). Do you want
an explicit "archive" action for dead deals (hidden from pipeline, still searchable)?
And should signed PDFs live inside the app's backup (yes, recommended) or on a file share?

**18. Where does the customer sign?** On-device signature was chosen for the field phase.
Open detail: your device (Android tablet? phone?) and whether the customer also gets an
emailed copy immediately from the tech's screen. HTTPS must be live first (nginx card is
pending — flag it when phase 4 nears).

---

## C. Ideas worth considering (no commitment)

**19. Weekly pipeline + orders-needed email.** A Monday-morning summary: deals with no
activity in X days, offers aging, parts overdue to machines, POs late, min-stock hits.
Cheap to build once data exists (phase 2+), high trust-builder. Say the word and it goes
on the board.

**20. Deal templates for repeating jobs.** If jobs like "PTI lane installation" always
produce the same document set (offer → checklist → work order → protocol), a deal template
could pre-create the checklist as timeline tasks. Only if you feel the repetition — skip
otherwise.

**21. Customer equipment portal-lite (much later).** A read-only page per customer
("your machines, their service dates, your documents") to send instead of answering
emails. Phase 5+ territory; mentioned so the equipment registry design keeps it possible.

**22. Barcode/QR labels on machines.** A printed QR on each machine that opens its record
on a phone. Makes van/warehouse flows faster and field work smoother. Cheap once machines
have records (label printer + one route).

**23. "Who quoted best" analytics.** Live funnel stats (offered → accepted, average
discount on accepted deals, best-selling items) come free from the deal links — like the
stats you built the hard way in MH fin analitike, but live and per-2026+. Decide later
which 3–5 numbers should be on the dashboard home page.

**24. Historia docet — old-documents sidebar.** When creating an offer for an existing
customer, show their last 5 offers + what was sold to them (from the live data). Small
feature, big "this app knows us" feeling. Phase 2.

**25. Multi-warehouse naming.** If you ever run more than one physical warehouse, the
custodian model already supports it (a warehouse is just a custodian row). Decide names
when it happens — nothing to change in the design.

---

## D. Answered decisions (for reference — do not re-litigate)

| Decision | Choice |
|---|---|
| Offers & invoices | Issued by the app; finance software keeps receipts/ePayments |
| Old data | Fresh start; no history import (customers seeding = open question #1) |
| Stock role | Operational ledger owned by the app; audit software keeps counting |
| Equipment registry | Yes: serials, per-machine history, maintenance reminders |
| Field use | Techs on phones; customer signs on device |
| First release | Customers + deals + offer, then invoice |
| Small parts | Not tracked at all (untracked regime default) |
| Donor parts | Tracked as shortfalls/debts, not inventory |
| Vans | Internal custodians, never customer rows |
| Document ↔ stock links | Optional evidence, never mandatory |
| Statuses | Derived from documents; only "new" (and the acceptance tap) are human |
| Renames/merges | Safe by design: links by id, snapshots for history, alias map for merges |
