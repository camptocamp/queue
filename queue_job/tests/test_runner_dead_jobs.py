# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)
from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase

from ..jobrunner.runner import Database


class TestRunnerDeadJobs(TransactionCase):
    """Check the query the runner uses to requeue or fail dead jobs."""

    def setUp(self):
        super().setUp()

        def _clean_queue_job():
            self.env["queue.job"].search([]).unlink()

        self.addCleanup(_clean_queue_job)

    def _dead_job(self, retry):
        job = self.env["queue.job"].with_delay(max_retries=5)._test_job()
        job.set_started()
        # Started long enough ago, and the lock row is not held by any worker.
        job.date_enqueued = datetime.now() - timedelta(minutes=1)
        job.retry = retry
        job.store()
        return job

    def _requeue_dead_jobs(self):
        self.env.flush_all()
        self.env.cr.execute(Database._query_requeue_dead_jobs(None))
        result = dict(self.env.cr.fetchall())
        self.env.invalidate_all()
        return result

    def test_dead_job_requeued(self):
        job = self._dead_job(retry=1)
        self.assertEqual(self._requeue_dead_jobs(), {job.uuid: "pending"})
        record = job.db_record()
        self.assertEqual(record.state, "pending")
        self.assertEqual(record.retry, 2)
        self.assertFalse(record.exc_name)

    def test_dead_job_failed_after_too_many_retries(self):
        # The retry count is compared before being incremented: the job fails
        # once it was already found dead more times than allowed retries.
        job = self._dead_job(retry=6)
        self.assertEqual(self._requeue_dead_jobs(), {job.uuid: "failed"})
        record = job.db_record()
        self.assertEqual(record.state, "failed")
        self.assertEqual(record.exc_name, "JobFoundDead")
        self.assertEqual(record.exc_info, "Job found dead after too many retries")
        self.assertEqual(record.exc_message, "Job found dead after too many retries")
