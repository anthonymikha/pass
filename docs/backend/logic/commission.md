# Commission (COM)

**Status: built** (`backend/billing/services.py`; settlement and add-only commission rows in the Django admin). The platform's percentage of each payment, and settling it with the payee.

## Lookup

**COM-1.** The commission **percent** for a payee on date D (UTC), with the payee's count N (COM-3):

1. Candidate rows: `applies_to` = the payee type (`club` or `coach`), `effective_from ≤ D`, `min_count ≤ N`.
2. If any candidate row names this payee (`club` = the club, or `coach` = the coach), use only those rows. Otherwise use only the default rows (both `club` and `coach` empty).
3. Order by `effective_from` newest first, then `min_count` highest first. Take the first row's `percent`.
4. If there is no row at all: percent = 0.

**COM-2.** Platform fee on a payment: `round_money(amount × percent / 100, currency)` (PAY-14). It is stored on the payment and never recomputed.

**COM-3.** The count N: while every commission row has `min_count = 0`, N is 0. Tiers are not switched on. When they are, the count definitions below apply, and this rule is replaced.
- Coach: the number of the coach's players (ACC-1), counting each user once.
- Club: non-cancelled sessions on the club's courts whose `starts_at` is in the 30 days before now (settled at the owner's review on 2026-11-16).

**COM-4.** Rates are changed only in the Django admin, by adding a complete new schedule (every tier, starting at `min_count = 0`) with a later `effective_from`. Old rows are never edited. Past payments are unaffected (COM-2).

## Settlement

**COM-10.** Settlement is recorded by a platform admin in the Django admin: setting `settled_at` on payments whose `paid_at` is set. A payment that is still due cannot be settled. A settled payment cannot go back to due (PAY-21).

**COM-11.** What a payee still owes the platform: the sum of `platform_fee` over its paid, unsettled payments, per currency (RPT-3).

## Example

Defaults seeded (SEED-2): club 10%, coach 10%, from the seed date. On 2027-03-01 the admin gives coach Sami a negotiated 7% from 2027-03-01 (`applies_to = coach`, `coach = Sami`, `min_count = 0`).

- Sami's payments checked in on 2027-02-20: Sami's own rows are not yet in effect, so default 10%.
- From 2027-03-01: Sami's own row, 7%.
- Another coach: default 10%.
