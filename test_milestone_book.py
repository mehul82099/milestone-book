#!/usr/bin/env python3
"""Tests for milestone_book. Run: python -m unittest -v"""

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date
from pathlib import Path

import milestone_book as mb


class ParseTests(unittest.TestCase):
    def test_parse_amount(self):
        self.assertEqual(mb.parse_amount("8000"), 800000)
        self.assertEqual(mb.parse_amount("8000.50"), 800050)

    def test_parse_amount_rejects(self):
        for bad in ("0", "-5", "10.005", "abc", "8,000", ""):
            with self.assertRaises(mb.MilestoneBookError):
                mb.parse_amount(bad)

    def test_format_indian_grouping(self):
        self.assertEqual(mb.format_paise(12345678), "1,23,456.78")
        self.assertEqual(mb.format_paise(100), "1.00")

    def test_bad_date(self):
        with self.assertRaises(mb.MilestoneBookError):
            mb.parse_date("20/11/2026")


class BookFixture(unittest.TestCase):
    def setUp(self):
        self.book = mb.MilestoneBook()
        self.book.add_project("Website Redesign", client="Kiran Traders")
        self.book.add_milestone("p1", "Design mockups", 800000,
                                due=date(2026, 11, 25))
        self.book.add_milestone("p1", "Final build", 1200000)


class ProjectTests(BookFixture):
    def test_lookup_by_name(self):
        self.assertEqual(self.book.get_project("website redesign")["id"],
                         "p1")

    def test_duplicate_rejected(self):
        with self.assertRaises(mb.MilestoneBookError):
            self.book.add_project("WEBSITE REDESIGN")

    def test_empty_name_rejected(self):
        with self.assertRaises(mb.MilestoneBookError):
            self.book.add_project("  ")

    def test_unknown_project(self):
        with self.assertRaises(mb.MilestoneBookError):
            self.book.get_project("p99")

    def test_empty_milestone_title_rejected(self):
        with self.assertRaises(mb.MilestoneBookError):
            self.book.add_milestone("p1", "  ", 100)


class LifecycleTests(BookFixture):
    def test_full_lifecycle_with_dates(self):
        self.book.advance("m1", date(2026, 11, 12), "pending")
        self.book.advance("m1", date(2026, 11, 14), "delivered")
        ms = self.book.advance("m1", date(2026, 11, 20), "approved")
        self.assertEqual(ms["status"], "paid")
        self.assertEqual(ms["dates"]["delivered"], "2026-11-12")
        self.assertEqual(ms["dates"]["approved"], "2026-11-14")
        self.assertEqual(ms["dates"]["paid"], "2026-11-20")

    def test_cannot_skip_steps(self):
        with self.assertRaises(mb.MilestoneBookError) as ctx:
            self.book.advance("m1", date(2026, 11, 12), "delivered")
        self.assertIn("cannot move to approved", str(ctx.exception))

    def test_cannot_pay_twice(self):
        for expect in ("pending", "delivered", "approved"):
            self.book.advance("m1", date(2026, 11, 12), expect)
        with self.assertRaises(mb.MilestoneBookError) as ctx:
            self.book.advance("m1", date(2026, 11, 13), "approved")
        self.assertIn("already paid", str(ctx.exception))

    def test_unknown_milestone(self):
        with self.assertRaises(mb.MilestoneBookError):
            self.book.advance("m99", date(2026, 11, 12), "pending")


class ReportFixture(BookFixture):
    def setUp(self):
        super().setUp()
        # m1 (8,000) paid; m2 (12,000) delivered, waiting on client
        for expect, d in (("pending", date(2026, 11, 5)),
                          ("delivered", date(2026, 11, 8)),
                          ("approved", date(2026, 11, 15))):
            self.book.advance("m1", d, expect)
        self.book.advance("m2", date(2026, 11, 10), "pending")


class ReportTests(ReportFixture):
    def test_project_statement(self):
        st = self.book.project_statement("p1")
        self.assertEqual(st["agreed"], 2000000)
        self.assertEqual(st["paid"], 800000)
        self.assertEqual(st["in_flight"], 1200000)
        self.assertEqual(st["pending"], 0)

    def test_outstanding_aging(self):
        rows = self.book.outstanding(as_of="2026-11-20")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["milestone"]["id"], "m2")
        self.assertEqual(r["project"]["client"], "Kiran Traders")
        # delivered on 2026-11-10, as of 2026-11-20 -> 10 days
        self.assertEqual(r["age_days"], 10)

    def test_outstanding_empty_when_all_paid(self):
        for expect in ("delivered", "approved"):
            self.book.advance("m2", date(2026, 11, 18), expect)
        self.assertEqual(self.book.outstanding(), [])

    def test_summary(self):
        s = self.book.summary()
        self.assertEqual(s["projects"], 1)
        self.assertEqual(s["milestones"], 2)
        self.assertEqual(s["agreed"], 2000000)
        self.assertEqual(s["paid"], 800000)
        self.assertEqual(s["unpaid"], 1200000)

    def test_export_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ms.csv"
            self.book.export_csv(out)
            with open(out, newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
        self.assertEqual(rows[0], ["milestone_id", "project", "client",
                                   "title", "amount", "status", "due",
                                   "delivered", "approved", "paid"])
        m1 = [r for r in rows if r[0] == "m1"][0]
        self.assertEqual(m1[4], "8,000.00")
        self.assertEqual(m1[5], "paid")
        self.assertEqual(m1[7], "2026-11-05")
        self.assertEqual(m1[9], "2026-11-15")
        m2 = [r for r in rows if r[0] == "m2"][0]
        self.assertEqual(m2[5], "delivered")
        self.assertEqual(m2[9], "")


class PersistenceTests(ReportFixture):
    def test_round_trip_and_lf_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "book.json"
            self.book.save(db)
            self.assertNotIn(b"\r\n", db.read_bytes())
            loaded = mb.MilestoneBook.load(db)
        self.assertEqual(loaded.summary(), self.book.summary())
        st = loaded.project_statement("p1")
        self.assertEqual(st["paid"], 800000)

    def test_failed_save_leaves_original_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "book.json"
            self.book.save(db)
            before = db.read_bytes()
            self.book.state["broken"] = object()
            try:
                with self.assertRaises(TypeError):
                    self.book.save(db)
                self.assertEqual(db.read_bytes(), before)
                leftovers = [p for p in Path(tmp).iterdir()
                             if p.name != "book.json"]
                self.assertEqual(leftovers, [])
            finally:
                del self.book.state["broken"]

    def test_corrupt_file_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "bad.json"
            db.write_text("{oops", encoding="utf-8")
            with self.assertRaises(mb.MilestoneBookError):
                mb.MilestoneBook.load(db)

    def test_missing_file_gives_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            loaded = mb.MilestoneBook.load(Path(tmp) / "none.json")
        self.assertEqual(loaded.summary()["projects"], 0)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "cli.json")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mb.main(["--db", self.db] + list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_full_flow(self):
        code, out, _ = self.run_cli("add-project", "--name", "Website Redesign",
                                    "--client", "Kiran Traders")
        self.assertEqual(code, 0)
        self.assertIn("p1", out)
        self.run_cli("add-milestone", "--project", "p1",
                     "--title", "Design mockups", "--amount", "8000.00",
                     "--due", "2026-11-25")
        self.run_cli("add-milestone", "--project", "p1",
                     "--title", "Final build", "--amount", "12000.00")
        code, out, _ = self.run_cli("deliver", "--milestone", "m1",
                                    "--date", "2026-11-05")
        self.assertIn("delivered", out)
        code, out, _ = self.run_cli("approve", "--milestone", "m1",
                                    "--date", "2026-11-08")
        self.assertIn("approved", out)
        code, out, _ = self.run_cli("pay", "--milestone", "m1",
                                    "--date", "2026-11-15")
        self.assertIn("paid", out)
        code, out, _ = self.run_cli("status", "--project", "p1")
        self.assertIn("Design mockups", out)
        self.assertIn("paid", out)
        self.assertIn("agreed Rs 20,000.00", out)
        code, out, _ = self.run_cli("outstanding")
        self.assertIn("Final build", out)
        self.assertIn("Kiran Traders", out)
        code, out, _ = self.run_cli("projects")
        self.assertIn("Kiran Traders", out)
        code, out, _ = self.run_cli("summary")
        self.assertIn("outstanding: Rs 12,000.00", out)
        out_path = str(Path(self.tmp.name) / "ms.csv")
        code, _, _ = self.run_cli("export-csv", out_path)
        self.assertEqual(code, 0)
        with open(out_path, newline="", encoding="utf-8") as f:
            self.assertEqual(len(list(csv.reader(f))), 3)

    def test_skip_step_error(self):
        self.run_cli("add-project", "--name", "App")
        self.run_cli("add-milestone", "--project", "p1", "--title", "Build",
                     "--amount", "5000")
        code, _, err = self.run_cli("pay", "--milestone", "m1")
        self.assertEqual(code, 2)
        self.assertIn("cannot move", err)

    def test_error_exit_code(self):
        code, _, err = self.run_cli("deliver", "--milestone", "m99")
        self.assertEqual(code, 2)
        self.assertIn("no such milestone", err)

    def test_all_paid_outstanding_message(self):
        self.run_cli("add-project", "--name", "App")
        self.run_cli("add-milestone", "--project", "p1", "--title", "Build",
                     "--amount", "5000")
        self.run_cli("deliver", "--milestone", "m1")
        self.run_cli("approve", "--milestone", "m1")
        self.run_cli("pay", "--milestone", "m1")
        code, out, _ = self.run_cli("outstanding")
        self.assertIn("nothing outstanding", out)


if __name__ == "__main__":
    unittest.main()
