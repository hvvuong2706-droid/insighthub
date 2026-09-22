"""Regression test for a real bug: arq's CLI resets logger levels after import.

Found by actually running the worker end-to-end and seeing document content
leak into stdout despite a module-level `setLevel(CRITICAL)` call. Root cause:
arq.cli.cli() imports WorkerSettings *before* calling
logging.config.dictConfig(default_log_config(...)), and dictConfig resets any
not-explicitly-listed logger's level back to NOTSET. This test reproduces that
exact ordering without needing a live Redis/Postgres/arq CLI subprocess.
"""

import io
import logging
import logging.config
import unittest
from contextlib import redirect_stdout

from arq.logs import default_log_config

import worker


class LogNoLeakTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(logging.getLogger("arq.worker").setLevel, logging.NOTSET)

    def test_silencing_survives_arq_dictconfig_reset(self):
        # Reproduce the exact bug: silence at "import time", then arq's CLI
        # runs dictConfig afterwards and used to undo it.
        logging.getLogger("arq.worker").setLevel(logging.CRITICAL)
        logging.config.dictConfig(default_log_config(False))
        self.assertEqual(
            logging.getLogger("arq.worker").level,
            logging.NOTSET,
            "dictConfig should reset the level here — if this fails, arq changed "
            "behavior and the fix (silencing from on_startup) may be unnecessary.",
        )

        worker.silence_arq_job_logger()  # must run *after* dictConfig, like on_startup does

        self.assertEqual(logging.getLogger("arq.worker").level, logging.CRITICAL)

    def test_job_start_line_with_marker_does_not_reach_stdout(self):
        logging.config.dictConfig(default_log_config(False))
        worker.silence_arq_job_logger()
        buf = io.StringIO()
        with redirect_stdout(buf):
            # This mirrors arq's own job-start log call shape (ref + args repr).
            logging.getLogger("arq.worker").info(
                "%6.2fs -> %s(%s)", 0.1, "job:run_ingestion", "SECRET_MARKER_MUST_NOT_LEAK"
            )
        self.assertNotIn("SECRET_MARKER_MUST_NOT_LEAK", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
