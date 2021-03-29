# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("Computing exception name for failed jobs")
    with api.Environment.manage():
        env = api.Environment(cr, SUPERUSER_ID, {})
        for job in env["queue.job"].search(
            [("state", "=", "failed"), ("exc_info", "!=", False)]
        ):
            exc_name = _get_exc_name(job)
            job.exc_name = exc_name


def _get_exc_name(job):
    # Just a list of common errors.
    # If you want to target others, add your own migration step for your db.
    exceptions = (
        "ValueError",
        "AttributeError",
        "TypeError",
        "IndexError",
        "KeyError",
        "AssertionError",
        "NotImplementedError",
        "OSError",
        "RuntimeError",
        "UnboundLocalError",
        "UnicodeError",
        "UnicodeEncodeError",
        "UnicodeDecodeError",
        "ZeroDivisionError",
        "IOError",
        "FileNotFoundError",
        "TimeoutError",
        "psycopg2.IntegrityError",
        "odoo.exceptions.AccessError",
        "odoo.exceptions.UserError",
        "odoo.exceptions.ValidationError",
        "odoo.addons.queue_job.exception.FailedJobError",
        "requests.exceptions.HTTPError",
        "requests.exceptions.MissingSchema",
    )
    for exc in exceptions:
        if exc in job.exc_info:
            return exc
