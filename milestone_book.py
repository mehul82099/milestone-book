#!/usr/bin/env python3
"""milestone-book: zero-dependency milestone and payment lifecycle CLI for
freelancers.

Split a project into milestones with agreed amounts. Move each one through
pending -> delivered -> approved -> paid, with dates. The book answers: how
much of this project is actually in the bank, what is waiting on the
client, and how long it has been waiting.

Python 3.9+, standard library only. One JSON file, offline, no accounts.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from datetime import date

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "milestone_book.json")

# Lifecycle: pending -> delivered -> approved -> paid.
# Every transition records its date; only forward moves are allowed.
STATUSES = ("pending", "delivered", "approved", "paid")
TRANSITIONS = {"pending": "delivered", "delivered": "approved",
               "approved": "paid"}


class MilestoneBookError(Exception):
    """User-facing error (bad input, unknown id, ...)."""


def today_iso():
    return date.today().isoformat()


def parse_date(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise MilestoneBookError("bad date %r (expected YYYY-MM-DD)" % text)


def parse_amount(text):
    """Rupees string -> integer paise; max 2 decimals, must be > 0."""
    text = (text or "").strip()
    if not re.fullmatch(r"\d+(\.\d{1,2})?", text):
        raise MilestoneBookError(
            "bad amount %r (e.g. 8000 or 8000.50, paise beyond 2 decimals "
            "not accepted)" % text)
    rupees, _, frac = text.partition(".")
    frac = (frac + "00")[:2]
    paise = int(rupees) * 100 + int(frac)
    if paise <= 0:
        raise MilestoneBookError("amount must be positive")
    return paise


def format_paise(paise):
    sign = "-" if paise < 0 else ""
    paise = abs(paise)
    s = str(paise // 100)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return "%s%s.%02d" % (sign, s, paise % 100)


def days_between(a_iso, b_iso):
    return (date.fromisoformat(b_iso) - date.fromisoformat(a_iso)).days


class MilestoneBook:
    def __init__(self):
        self.state = {"projects": [], "milestones": [],
                      "next_project_id": 1, "next_milestone_id": 1}

    # -- persistence ------------------------------------------------------

    @classmethod
    def load(cls, path):
        if not path.exists():
            return cls()
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise MilestoneBookError(
                "could not parse %s: %s" % (path, exc))
        book = cls()
        for key in state:
            if key in book.state:
                book.state[key] = state[key]
        return book

    def save(self, path):
        data = json.dumps(self.state, indent=2, ensure_ascii=False) + "\n"
        fd, tmp_name = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(data)
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # -- projects ---------------------------------------------------------

    def add_project(self, name, client="", notes=""):
        name = (name or "").strip()
        if not name:
            raise MilestoneBookError("project name must not be empty")
        if any(p["name"].lower() == name.lower()
               for p in self.state["projects"]):
            raise MilestoneBookError("project already exists: %s" % name)
        proj = {"id": "p%d" % self.state["next_project_id"], "name": name,
                "client": (client or "").strip(),
                "notes": (notes or "").strip(), "added": today_iso()}
        self.state["next_project_id"] += 1
        self.state["projects"].append(proj)
        return proj

    def get_project(self, ref):
        ref = (ref or "").strip()
        for p in self.state["projects"]:
            if p["id"] == ref or p["name"].lower() == ref.lower():
                return p
        raise MilestoneBookError("no such project: %s" % ref)

    # -- milestones -------------------------------------------------------

    def add_milestone(self, project_ref, title, amount_paise, due=None):
        proj = self.get_project(project_ref)
        title = (title or "").strip()
        if not title:
            raise MilestoneBookError("milestone title must not be empty")
        ms = {"id": "m%d" % self.state["next_milestone_id"],
              "project_id": proj["id"], "title": title,
              "amount_paise": amount_paise,
              "due": due.isoformat() if due else "",
              "status": "pending",
              "dates": {"pending": today_iso()}}
        self.state["next_milestone_id"] += 1
        self.state["milestones"].append(ms)
        return ms

    def get_milestone(self, ref):
        ref = (ref or "").strip()
        for m in self.state["milestones"]:
            if m["id"] == ref:
                return m
        raise MilestoneBookError("no such milestone: %s" % ref)

    def advance(self, milestone_ref, when, expect):
        """Move one step forward in the lifecycle, stamping the date.
        `expect` is the required current status for this transition."""
        ms = self.get_milestone(milestone_ref)
        if ms["status"] == "paid":
            raise MilestoneBookError(
                "%s is already paid - lifecycle complete" % ms["id"])
        if ms["status"] != expect:
            raise MilestoneBookError(
                "%s is %s - cannot move to %s from here (expected %s)"
                % (ms["id"], ms["status"], TRANSITIONS[expect], expect))
        nxt = TRANSITIONS[ms["status"]]
        ms["status"] = nxt
        ms["dates"][nxt] = when.isoformat()
        return ms

    # -- reports ----------------------------------------------------------

    def project_statement(self, project_ref):
        proj = self.get_project(project_ref)
        mss = [m for m in self.state["milestones"]
               if m["project_id"] == proj["id"]]
        totals = {s: 0 for s in STATUSES}
        for m in mss:
            totals[m["status"]] += m["amount_paise"]
        agreed = sum(m["amount_paise"] for m in mss)
        return {"project": proj, "milestones": mss, "agreed": agreed,
                "paid": totals["paid"],
                "in_flight": totals["delivered"] + totals["approved"],
                "pending": totals["pending"]}

    def outstanding(self, as_of=None):
        """Unpaid milestones grouped by client, oldest first. Aging = days
        since the milestone's current status started."""
        as_of = as_of or today_iso()
        rows = []
        for m in self.state["milestones"]:
            if m["status"] == "paid":
                continue
            proj = self.get_project(m["project_id"])
            since = m["dates"][m["status"]]
            rows.append({"milestone": m, "project": proj,
                         "age_days": days_between(since, as_of)})
        rows.sort(key=lambda r: (-r["age_days"],
                                 r["milestone"]["amount_paise"]))
        return rows

    def export_csv(self, out_path):
        with open(out_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["milestone_id", "project", "client", "title",
                        "amount", "status", "due", "delivered", "approved",
                        "paid"])
            for m in self.state["milestones"]:
                proj = self.get_project(m["project_id"])
                d = m["dates"]
                w.writerow([m["id"], proj["name"], proj["client"],
                            m["title"], format_paise(m["amount_paise"]),
                            m["status"], m["due"], d.get("delivered", ""),
                            d.get("approved", ""), d.get("paid", "")])

    def summary(self):
        agreed = sum(m["amount_paise"] for m in self.state["milestones"])
        paid = sum(m["amount_paise"] for m in self.state["milestones"]
                   if m["status"] == "paid")
        return {"projects": len(self.state["projects"]),
                "milestones": len(self.state["milestones"]),
                "agreed": agreed, "paid": paid,
                "unpaid": agreed - paid}


# -- CLI --------------------------------------------------------------------

def _when(args):
    return parse_date(args.date) if getattr(args, "date", None) \
        else date.today()


def cmd_add_project(book, args):
    proj = book.add_project(args.name, args.client, args.notes)
    print("added project %s: %s%s"
          % (proj["id"], proj["name"],
             ("  (client: %s)" % proj["client"]) if proj["client"] else ""))


def cmd_projects(book, args):
    if not book.state["projects"]:
        print("no projects yet")
        return
    for p in book.state["projects"]:
        st = book.project_statement(p["id"])
        print("%-4s  %-26s  agreed Rs %-10s  paid Rs %-10s  (%s)"
              % (p["id"], p["name"], format_paise(st["agreed"]),
                 format_paise(st["paid"]),
                 p["client"] or "no client"))


def cmd_add_milestone(book, args):
    ms = book.add_milestone(args.project, args.title,
                            parse_amount(args.amount),
                            parse_date(args.due) if args.due else None)
    print("added milestone %s: %s (Rs %s)"
          % (ms["id"], ms["title"], format_paise(ms["amount_paise"])))


def _advance(cmd):
    def run(book, args):
        ms = cmd(book, args)
        print("%s: %s -> %s on %s (Rs %s)"
              % (ms["id"], ms["title"], ms["status"],
                 ms["dates"][ms["status"]],
                 format_paise(ms["amount_paise"])))
    return run


def cmd_status(book, args):
    st = book.project_statement(args.project)
    proj = st["project"]
    print("%s (%s)%s" % (proj["name"], proj["id"],
                         ("  client: " + proj["client"])
                         if proj["client"] else ""))
    for m in st["milestones"]:
        due = ("  due %s" % m["due"]) if m["due"] else ""
        when = m["dates"][m["status"]]
        print("  %-4s  %-30s  Rs %-10s  %-9s since %s%s"
              % (m["id"], m["title"], format_paise(m["amount_paise"]),
                 m["status"], when, due))
    print("  agreed Rs %s  |  paid Rs %s  |  in flight Rs %s  |  "
          "not started Rs %s"
          % (format_paise(st["agreed"]), format_paise(st["paid"]),
             format_paise(st["in_flight"]), format_paise(st["pending"])))


def cmd_outstanding(book, args):
    rows = book.outstanding()
    if not rows:
        print("nothing outstanding - every milestone is paid")
        return
    for r in rows:
        m = r["milestone"]
        proj = r["project"]
        print("%-4s  %-24s  %-18s  %-14s  Rs %-10s  %-9s for %d day(s)%s"
              % (m["id"], m["title"][:24], proj["name"][:18],
                 (proj["client"] or "-")[:14],
                 format_paise(m["amount_paise"]),
                 m["status"], r["age_days"],
                 ("  (due %s)" % m["due"]) if m["due"] else ""))


def cmd_export_csv(book, args):
    book.export_csv(args.path)
    print("wrote %s" % args.path)


def cmd_summary(book, args):
    s = book.summary()
    print("projects: %d   milestones: %d   agreed: Rs %s   paid: Rs %s   "
          "outstanding: Rs %s"
          % (s["projects"], s["milestones"], format_paise(s["agreed"]),
             format_paise(s["paid"]), format_paise(s["unpaid"])))


def build_parser():
    p = argparse.ArgumentParser(
        prog="milestone-book",
        description="Milestone and payment lifecycle record for "
                    "freelancers. Offline, one JSON file.")
    p.add_argument("--db", default=DEFAULT_DB,
                   help="store file (default: milestone_book.json next to "
                        "this script)")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("add-project", help="register a project")
    sp.add_argument("--name", required=True)
    sp.add_argument("--client", default="")
    sp.add_argument("--notes", default="")
    sp.set_defaults(func=cmd_add_project)

    sp = sub.add_parser("projects", help="list projects with totals")
    sp.set_defaults(func=cmd_projects)

    sp = sub.add_parser("add-milestone", help="add a milestone")
    sp.add_argument("--project", required=True, help="id or exact name")
    sp.add_argument("--title", required=True)
    sp.add_argument("--amount", required=True, help="rupees, e.g. 8000.00")
    sp.add_argument("--due", default=None, help="YYYY-MM-DD (optional)")
    sp.set_defaults(func=cmd_add_milestone)

    for name, expect in (("deliver", "pending"),
                         ("approve", "delivered"),
                         ("pay", "approved")):
        sp = sub.add_parser(name, help="mark a milestone %s"
                            % TRANSITIONS[expect])
        sp.add_argument("--milestone", required=True, help="milestone id")
        sp.add_argument("--date", default=None,
                        help="YYYY-MM-DD (default: today)")
        sp.set_defaults(func=_advance(
            lambda b, a, e=expect: b.advance(a.milestone, _when(a), e)))

    sp = sub.add_parser("status", help="project statement")
    sp.add_argument("--project", required=True, help="id or exact name")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("outstanding",
                        help="unpaid milestones, oldest first, with aging")
    sp.set_defaults(func=cmd_outstanding)

    sp = sub.add_parser("export-csv", help="export all milestones to CSV")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_export_csv)

    sp = sub.add_parser("summary", help="one-line store summary")
    sp.set_defaults(func=cmd_summary)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    from pathlib import Path
    db = Path(args.db)
    try:
        book = MilestoneBook.load(db)
        args.func(book, args)
        book.save(db)
    except MilestoneBookError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
