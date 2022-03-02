# Copyright 2022 Camptocamp SA (https://www.camptocamp.com).
# @author Iván Todorovich <ivan.todorovich@camptocamp.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import traceback
from datetime import timedelta
from io import StringIO

from psycopg2 import OperationalError

from odoo import _, api, fields, models, tools
from odoo.service.model import PG_CONCURRENCY_ERRORS_TO_RETRY

from odoo.addons.queue_job.controllers.main import PG_RETRY
from odoo.addons.queue_job.exception import (
    FailedJobError,
    NothingToDoJob,
    RetryableJobError,
)
from odoo.addons.queue_job.job import Job

# TODO: increase this number and make it configurable
QUEUE_JOB_RUNNER_BATCH = 50


_logger = logging.getLogger(__name__)


class QueueJob(models.Model):
    _inherit = "queue.job"

    @api.model
    def _get_jobs_to_run(self, limit=None):
        # TODO: This method should fetch job in the order they are meant
        # to be executed, respecting channel priority and capacity.
        # NOTE: Ideally we should only fetch jobs in "pending" state,
        # but we can find "started" jobs if the runner stopped abruptly.
        # We should never find "enqueued" jobs but anyway it doesn't hurt.
        # Before running them, jobs will be locked and skiped otherwise, so..
        jobs = self.search(
            [
                ("state", "in", ("pending", "started", "enqueued")),
                "|",
                ("eta", "=", False),
                ("eta", "<=", fields.Datetime.now()),
            ],
            limit=limit,
        )
        return jobs

    def _lock(self):
        """Lock jobs for update

        This makes sure we don't run the same queue.job twice, at the same time.

        NOTE: Not sure it makes sense here, as we are not running jobs concurrently.

        :returns: queue.job recordset that have been locked
        """
        if self.ids:
            try:
                with tools.mute_logger("odoo.sql_db"):
                    with self.env.cr.savepoint(flush=False):
                        self.env.cr.execute(
                            """
                            SELECT id
                            FROM queue_job
                            WHERE id IN %s
                            FOR NO KEY UPDATE SKIP LOCKED
                            """,
                            (tuple(self.ids),),
                        )
                        return self.browse([r[0] for r in self.env.cr.fetchall()])
            except OperationalError as e:
                if e.pgcode in PG_CONCURRENCY_ERRORS_TO_RETRY:
                    return False
                else:
                    raise e
        return True

    @api.model
    def _job_runner(self):
        """Short-lived job runner, triggered by async crons"""
        # pylint: disable=C901
        # Get and lock jobs to run
        jobs = self._get_jobs_to_run(limit=QUEUE_JOB_RUNNER_BATCH)
        if not jobs:
            return
        if not jobs._lock():
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug("Unable to lock jobs.. postponed")
            cron = self.sudo().env.ref("queue_job_test.queue_job_cron")
            cron._trigger(at=fields.Datetime.now() + timedelta(seconds=PG_RETRY))
            return
        # Process jobs
        for job in jobs:
            # TODO: Do we really need this class? It could simply be queue.job
            _job = Job._load_from_db_record(job)
            # Set job as started
            _job.set_started()
            _job.store()
            self.flush()
            self.env.cr.commit()
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug("%s started", job.uuid)

            # Process job
            try:
                try:
                    with self.env.cr.savepoint():
                        _job.perform()
                        _job.set_done()
                        _job.store()
                except OperationalError as err:
                    # Automatically retry the typical transaction serialization errors
                    if err.pgcode not in PG_CONCURRENCY_ERRORS_TO_RETRY:
                        raise
                    message = tools.ustr(err.pgerror, errors="replace")
                    _job.postpone(result=message, seconds=PG_RETRY)
                    _job.set_pending(reset_retry=False)
                    _job.store()
                    if _logger.isEnabledFor(logging.DEBUG):
                        _logger.debug("%s OperationalError, postponed", job)

            except NothingToDoJob as err:
                if str(err):
                    msg = str(err)
                else:
                    msg = _("Job interrupted and set to Done: nothing to do.")
                _job.set_done(msg)
                _job.store()

            except RetryableJobError as err:
                # delay the job later, requeue
                _job.postpone(result=str(err), seconds=5)
                _job.set_pending(reset_retry=False)
                _job.store()
                if _logger.isEnabledFor(logging.DEBUG):
                    _logger.debug("%s postponed", job)

            except (FailedJobError, Exception):
                buff = StringIO()
                traceback.print_exc(file=buff)
                _logger.error(buff.getvalue())
                _job.set_failed(exc_info=buff.getvalue())
                _job.store()

            # Commit after processing job
            self.env["base"].flush()
            self.env.cr.commit()

        # In the end, if we still have jobs to run after we processed this batch, trigger again
        # This ensures an endless loop of processing jobs, until all jobs are processed
        if self._get_jobs_to_run(limit=1):
            cron = self.sudo().env.ref("queue_job_test.queue_job_cron")
            cron._trigger()

    def _trigger_cron(self):
        records = self.filtered(lambda r: r.state == "pending")
        if not records:
            return
        cron = self.sudo().env.ref("queue_job_test.queue_job_cron")
        # Trigger immediate runs
        immediate = any(not rec.eta for rec in records)
        if immediate:
            cron._trigger()
        # Trigger delayed eta runs
        delayed_etas = {rec.eta for rec in records if rec.eta}
        if delayed_etas:
            cron._trigger(at=list(delayed_etas))

    @api.model_create_multi
    def create(self, vals_list):
        # When jobs are created, also create the cron trigger
        records = super().create(vals_list)
        records._trigger_cron()
        return records

    def write(self, vals):
        # When a job state or eta changes, make sure a cron trigger is created
        res = super().write(vals)
        if "state" in vals or "eta" in vals:
            self._trigger_cron()
        return res
