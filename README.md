# milestone-book

A zero-dependency command-line milestone and payment lifecycle record for
freelancers. Split a project into milestones with agreed amounts, move each
one through pending, delivered, approved, paid - with dates - and the book
answers: how much of this project is actually in the bank, what is waiting
on the client, and how long it has been waiting.

Single Python file, standard library only (Python 3.9+). Fully offline; all
data lives in one local JSON file you own.

## Why this exists

On Razorpay's public "Fix My Itch" list, one entry asks: "Why do
freelancers ghost projects after partial payments without accountability
systems?" (page fetched and entry re-verified on 2026-11-20;
https://razorpay.com/m/fix-my-itch/). That list is curated by Razorpay - it
shows the problem was submitted and published, not how common it is.

This tool cannot stop anyone ghosting - no record book can. What it does is
make the money state unambiguous on the freelancer's own side: every
milestone has a state and a date, so "the client still owes Rs 12,000 and it
has been sitting approved for 10 days" is a fact on screen, not a feeling.
That record is also exactly what you want in hand when following up or
deciding whether to start the next milestone.

## What it does

- **Projects** with client name and notes.
- **Milestones** with agreed amount and optional due date.
- **A strict lifecycle** - `deliver`, `approve`, `pay` each move a
  milestone exactly one step forward (pending, delivered, approved, paid)
  and stamp the date. Skipping steps or paying twice is rejected.
- **Project statement** - per milestone: status since when, due date;
  totals: agreed / paid / in flight / not started.
- **Outstanding list** - every unpaid milestone across projects, oldest
  first, with aging in days since it reached its current state.
- **CSV export** of all milestones with their transition dates.

## What it does NOT do (limits)

- **It creates no accountability for the other side.** No contracts, no
  escrow, no reminders sent to clients - it records what happened.
- **Not invoicing or GST.** No tax, no invoice documents, no payment
  links (see the sibling tool invoice-ledger for invoice-side records).
- **Amounts are as agreed, in rupees you type** - integer paise internally,
  no currency conversion.
- **Dates are as entered** (default today); the lifecycle enforces order of
  steps, not that dates are in the past.
- **Durability:** saves are atomic (write to a temp file, then replace the
  store), and a failed save leaves the previous store intact - that behavior
  is covered by tests. Beyond that there are no guarantees against power
  loss mid-write or two people editing the same file at once.

## Landscape note (checked 2026-11-20)

Dated searches on 2026-11-20 for `freelance milestone payment tracker cli
open source` and `freelancer client payment milestone tracking software`
surfaced hosted milestone-billing / client-portal SaaS and some
invoice/payment-log CLI repos. This project's scope is the milestone
**lifecycle state machine** - strict forward transitions with dated steps
and aging - in a single dependency-free offline Python file. That is a
statement about what those searches found on that date, not a claim that no
similar tool exists.

## Install and quick start

Requires Python 3.9+. No dependencies.

```bash
python3 milestone_book.py --help
```

Walkthrough (each command saves automatically to `--db`, default
`milestone_book.json`):

```bash
python3 milestone_book.py add-project --name "Website Redesign" \
  --client "Kiran Traders"
python3 milestone_book.py add-milestone --project p1 \
  --title "Design mockups" --amount 8000.00 --due 2026-11-25
python3 milestone_book.py add-milestone --project p1 \
  --title "Final build" --amount 12000.00

python3 milestone_book.py deliver --milestone m1 --date 2026-11-05
python3 milestone_book.py approve --milestone m1 --date 2026-11-08
python3 milestone_book.py pay     --milestone m1 --date 2026-11-15

python3 milestone_book.py status --project p1   # full statement
python3 milestone_book.py outstanding           # what is owed, oldest first
python3 milestone_book.py export-csv milestones.csv
```

Example `status --project p1` output:

```
Website Redesign (p1)  client: Kiran Traders
  m1    Design mockups                  Rs 8,000.00    paid      since 2026-11-15  due 2026-11-25
  m2    Final build                     Rs 12,000.00   pending   since 2026-11-20
  agreed Rs 20,000.00  |  paid Rs 8,000.00  |  in flight Rs 0.00  |  not started Rs 12,000.00
```

Projects can be referred to by id (`p1`) or by exact name; milestones by id
(`m1`). `--date` defaults to today.

## Data and tests

- Store: one JSON file (`--db`, default `milestone_book.json` next to the
  script), written with LF line endings and atomic replace. A failed
  serialization leaves the previous file untouched (tested).
- Money is stored as integer paise (no float drift); amounts with more than
  two decimal places, and zero or negative amounts, are rejected.
- Tests: 26 unit tests (`python3 -m unittest -v`) covering money parsing,
  the lifecycle state machine (skip-step and double-pay rejection), project
  statements, outstanding aging, CSV export, persistence, and the CLI. CI
  runs them on ubuntu-24.04 and windows-latest, Python 3.9 and 3.13.

## License

MIT - see [LICENSE](LICENSE). Copyright (c) 2026 Mehul Jhabak.
