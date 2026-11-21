# billing models

Source: [backend/billing/models.py](../../../backend/billing/models.py). Tables: `payments`, `commission_rates`.

There is no payment gateway yet. Money changes hands at the court; these tables record that it did and what the platform is owed.

## Payment (`payments`)

One row per amount **owed** by one person to one payee for one session. A row says the money is due; `paid_at` says it was received.

| Field | Meaning |
|---|---|
| `session` | What it is for |
| `payer` | Who owes it |
| `club` **or** `coach` | The payee. Exactly one is set |
| `amount`, `currency` | What is owed |
| `platform_fee` | The platform's cut of this payment, in the same currency, fixed at creation |
| `method` | Empty until paid. `offline` today; `online` once a gateway exists |
| `payer_marked_at` | When the payer said "I paid" (review 2026-11-20, [PAY-26](../logic/check-in-and-payments.md#marking-paid)). A claim only: the row stays due until `paid_at` is set |
| `paid_at` | When the payee received it. Empty (and not waived) = still due |
| `waived_at` | When the payee gave it up ([PAY-25](../logic/check-in-and-payments.md#marking-paid)). Set = not owed |
| `settled_at` | When the platform's cut was settled with the payee. Empty = still owed |

### When rows are created

A confirmed session is **billed** a day after it ends, once check-in has closed, from the people who checked in (review 2026-11-17). Which rows are created, how a fee is split, and who ticks them: [PAY-9 to PAY-27](../logic/check-in-and-payments.md).

### Reading the money

```python
from django.db.models import Sum, F

# a club's collected revenue and what it keeps, per currency (unpaid rows have no paid_at, so they drop out)
Payment.objects.filter(club=club, paid_at__range=(a, b)).values("currency").annotate(
    gross=Sum("amount"), fees=Sum("platform_fee"), net=Sum(F("amount") - F("platform_fee")),
)

# what players still owe a club
Payment.objects.filter(club=club, paid_at__isnull=True, waived_at__isnull=True).values("currency").annotate(due=Sum("amount"))

# what a club still owes the platform
Payment.objects.filter(club=club, settled_at__isnull=True).values("currency").annotate(owed=Sum("platform_fee"))
```

Amounts in different currencies are never added together; always group by `currency`.

Payments are permanent records. Sessions, users and clubs that have payments cannot be deleted.

## CommissionRate (`commission_rates`)

The platform's percentage, with history and room for tiers.

| Field | Meaning |
|---|---|
| `applies_to` | `club` or `coach` |
| `club`, `coach` | Both empty = default schedule. One set = negotiated rate for that payee |
| `min_count` | Tier lower bound; 0 for a flat rate |
| `percent` | The cut |
| `effective_from` | Date the row starts to apply |

A **schedule** is the set of rows sharing a target and an `effective_from` date. Today every schedule is a single row with `min_count` 0.

### Lookup

The rules are [COM-1 to COM-4](../logic/commission.md). In code:

```python
rows = CommissionRate.objects.filter(applies_to="coach", effective_from__lte=today, min_count__lte=count)
rate = (rows.filter(coach=coach).order_by("-effective_from", "-min_count").first()
        or rows.filter(coach__isnull=True, club__isnull=True).order_by("-effective_from", "-min_count").first())
platform_fee = round_money(amount * rate.percent / 100, currency)   # COM-2
```

### Rules for editing schedules

- Never edit old rows to change a rate. Add new rows with a later `effective_from`.
- A new schedule must be complete: every tier, starting at `min_count` 0. A partial schedule mixes old and new rates.
- Past payments are unaffected because each stores its own `platform_fee`.

### The count (for tiers, later)

See [COM-3](../logic/commission.md). While only `min_count` 0 rows exist, the count is 0.

Example of a tiered coach schedule, when tiers are switched on:

| min_count | percent | effective_from |
|---|---|---|
| 0 | 10 | 2027-01-01 |
| 6 | 8 | 2027-01-01 |
| 11 | 6 | 2027-01-01 |

A coach with 7 players matches the rows for 0 and 6; the highest wins: 8%.

## Used together with

- `bookings.Session` and `SessionParticipant` decide what is created and when.
- `venues.Club` and `accounts.User` are the payees.
- Journey: [booking-and-payment](../flows/booking-and-payment.md).
