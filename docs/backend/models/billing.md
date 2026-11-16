# billing models

Source: [backend/billing/models.py](../../../backend/billing/models.py). Tables: `payments`, `commission_rates`.

There is no payment gateway yet. Money changes hands at the court; these tables record that it did and what the platform is owed.

## Payment (`payments`)

One row per amount paid by one person to one payee for one session.

| Field | Meaning |
|---|---|
| `session` | What was paid for |
| `payer` | Who paid |
| `club` **or** `coach` | The payee. Exactly one is set |
| `amount`, `currency` | What was paid |
| `platform_fee` | The platform's cut of this payment, in the same currency, fixed at creation |
| `method` | `offline` today; `online` once a gateway exists |
| `paid_at` | When it counts as paid |
| `settled_at` | When the platform's cut was settled with the payee. Empty = still owed |

### When rows are created

A confirmed session counts as paid when its **booker checks in**. That check-in creates, in one transaction:

| Payment | Payer | Payee | Amount |
|---|---|---|---|
| Court fee | booker | the court's club | `price − discount_amount` + approved rentals |
| Coach fee, single payer | `coach_fee_payer` | the coach | `coach_fee` |
| Coach fee, split (default) | each accepted team member | the coach | `coach_fee` ÷ members; any rounding remainder goes on the first share |

No check-in by the booker means no payment rows. Creation must be safe to repeat: if rows already exist for the session, do nothing.

### Reading the money

```python
from django.db.models import Sum, F

# a club's revenue and what it keeps, per currency
Payment.objects.filter(club=club, paid_at__range=(a, b)).values("currency").annotate(
    gross=Sum("amount"), fees=Sum("platform_fee"), net=Sum(F("amount") - F("platform_fee")),
)

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

To find the rate for a payee on a date:

1. Use the payee's own rows if any are in effect; otherwise the default rows for that `applies_to`.
2. Keep rows with `effective_from` ≤ the date and `min_count` ≤ the payee's count.
3. Order by newest `effective_from`, then highest `min_count`. Take the first.

```python
rows = CommissionRate.objects.filter(applies_to="coach", effective_from__lte=today, min_count__lte=count)
rate = (rows.filter(coach=coach).order_by("-effective_from", "-min_count").first()
        or rows.filter(coach__isnull=True, club__isnull=True).order_by("-effective_from", "-min_count").first())
platform_fee = amount * rate.percent / 100
```

### Rules for editing schedules

- Never edit old rows to change a rate. Add new rows with a later `effective_from`.
- A new schedule must be complete: every tier, starting at `min_count` 0. A partial schedule mixes old and new rates.
- Past payments are unaffected because each stores its own `platform_fee`.

### The count (for tiers, later)

- Coach: distinct active players (accepted coaching connections plus active members of their teams).
- Club: booking volume; the time window is not decided.

While only `min_count` 0 rows exist, the count does not matter.

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
