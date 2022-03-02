# Copyright 2022 Camptocamp SA (https://www.camptocamp.com).
# @author Iván Todorovich <ivan.todorovich@camptocamp.com>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import random
import time

from odoo import models
from odoo.exceptions import UserError

from odoo.addons.queue_job.exception import RetryableJobError


class QueueJobChannel(models.Model):
    _inherit = "queue.job.channel"

    def _process_fake_job(self, success_rate=1.0, retryable=True):
        time.sleep(random.uniform(0, 2))
        fail_rate = 1.0 - success_rate
        if random.uniform(0, 1) < fail_rate:
            if retryable:
                raise RetryableJobError("Fake error")
            else:
                raise UserError("Fake error")

    def generate_fake_jobs(self):
        for rec in self:
            for __ in range(100):
                rec.with_delay()._process_fake_job(success_rate=0.7)
