# Copyright 2016-2019 Camptocamp SA
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo.tests import common

from odoo.addons.queue_job.job import QUEUE_JOB_LOCK_KEY, Job


class JobCommonCase(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.queue_job = cls.env["queue.job"]
        cls.user = cls.env["res.users"]
        cls.method = cls.env["test.queue.job"].testing_method

    def _create_job(self):
        test_job = Job(self.method)
        test_job.store()
        stored = Job.db_records_from_uuids(self.env, [test_job.uuid])
        self.assertEqual(len(stored), 1)
        return stored

    def _get_demo_job(self, uuid):
        # job created during load of demo data
        job = self.env["queue.job"].search([("uuid", "=", uuid)], limit=1)
        self.assertTrue(
            job,
            f"Demo data queue job {uuid!r} should be loaded in order "
            "to make this test work",
        )
        return job

    def is_job_locked(self, job, cr=None):
        base_query = "SELECT 1 FROM queue_job WHERE uuid = %s"
        query_lock_shared, query_unlock_shared = (
            f"{base_query} AND pg_try_advisory_lock_shared(%s, id);",
            f"{base_query} AND pg_advisory_unlock_shared(%s, id);",
        )
        args = job.uuid, QUEUE_JOB_LOCK_KEY
        with self.env.registry.cursor() as cr:
            cr.execute(query_lock_shared, args)
            if not cr.fetchone():
                return True
            cr.execute(query_unlock_shared, args)
        return False
