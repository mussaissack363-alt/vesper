#!/usr/bin/env python3
"""Dynamic response-length system tests: splitter unit tests + Flask test client."""
import sys
import unittest
from unittest import mock

from groq_brain_v3 import split_spoken_reply
import vesper_server


class TestSplitter(unittest.TestCase):
    def test_plain_reply_untouched(self):
        r = "Hey. What's up?"
        spoken, full = split_spoken_reply(r)
        self.assertEqual(spoken, r)
        self.assertEqual(full, r)

    def test_basic_split(self):
        r = ("Spoken Summary: Three fixes, all applied.\n"
             "Full Answer: 1. Foo\n2. Bar\n3. Baz")
        spoken, full = split_spoken_reply(r)
        self.assertEqual(spoken, "Three fixes, all applied.")
        # full = body only; the chat UI renders the raw reply (headers included)
        self.assertEqual(full, "1. Foo\n2. Bar\n3. Baz")
        self.assertIn("2. Bar", full)

    def test_case_and_bold_and_hash(self):
        for head in ("**Spoken Summary:**", "## Spoken Summary", "spoken summary -"):
            r = f"{head} It works.\nFull Answer: details here"
            spoken, full = split_spoken_reply(r)
            self.assertEqual(spoken, "It works.")
            self.assertEqual(full, "details here")

    def test_multiline_spoken_until_full_marker(self):
        r = ("Spoken Summary: First line,\nstill the summary,\nand a third.\n"
             "Full Answer:\n- item one\n- item two")
        spoken, full = split_spoken_reply(r)
        self.assertIn("First line,", spoken)
        self.assertIn("and a third.", spoken)
        self.assertNotIn("item one", spoken)
        self.assertIn("- item two", full)

    def test_missing_full_marker_keeps_everything(self):
        r = "Spoken Summary: Just this, then rambling\nwith no second marker."
        spoken, full = split_spoken_reply(r)
        self.assertEqual(full, r.strip())

    def test_empty_summary_falls_back(self):
        r = "Spoken Summary:\nFull Answer: details"
        spoken, full = split_spoken_reply(r)
        self.assertEqual(spoken, r.strip())

    def test_empty_reply(self):
        self.assertEqual(split_spoken_reply(""), ("", ""))


class TestServerResponses(unittest.TestCase):
    def setUp(self):
        vesper_server.app.config["TESTING"] = True
        self.client = vesper_server.app.test_client()

    def test_chat_returns_spoken_field(self):
        reply = ("Spoken Summary: Two-step fix, easy.\n"
                 "Full Answer: Step 1: clear the cache.\nStep 2: restart the server.")
        with mock.patch.object(vesper_server, "think", return_value=reply), \
             mock.patch.object(vesper_server, "last_emotion", return_value="smug"):
            res = self.client.post("/api/chat", json={"message": "fix my build"})
        data = res.get_json()
        self.assertEqual(data["reply"], reply)
        self.assertEqual(data["spoken"], "Two-step fix, easy.")
        self.assertEqual(data["emotion"], "smug")

    def test_chat_casual_reply_spoken_equals_reply(self):
        with mock.patch.object(vesper_server, "think", return_value="Fine, whatever."), \
             mock.patch.object(vesper_server, "last_emotion", return_value="calm"):
            res = self.client.post("/api/chat", json={"message": "hey"})
        data = res.get_json()
        self.assertEqual(data["spoken"], "Fine, whatever.")
        self.assertEqual(data["reply"], "Fine, whatever.")

    def test_device_command_bypasses_splitter(self):
        # PC command path returns before think(); must still be well-formed.
        # 'Opening ...' hits the fallback-emotion playful keyword list.
        with mock.patch.object(vesper_server, "DEVICE_TYPE", "pc"), \
             mock.patch.object(vesper_server, "handle_pc_command", return_value="Opening chrome..."):
            res = self.client.post("/api/chat", json={"message": "open chrome"})
        data = res.get_json()
        self.assertEqual(data["reply"], "Opening chrome...")
        self.assertEqual(data["spoken"], "Opening chrome...")   # command replies speak verbatim
        self.assertEqual(data["emotion"], "playful")


if __name__ == "__main__":
    unittest.main(verbosity=2)
