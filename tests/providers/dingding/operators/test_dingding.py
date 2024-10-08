#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from __future__ import annotations

from unittest import mock

from airflow.models.dag import DAG
from airflow.providers.dingding.operators.dingding import DingdingOperator
from airflow.utils import timezone

DEFAULT_DATE = timezone.datetime(2017, 1, 1)


class TestDingdingOperator:
    _config = {
        "dingding_conn_id": "dingding_default",
        "message_type": "text",
        "message": "Airflow dingding webhook test",
        "at_mobiles": ["123", "456"],
        "at_all": False,
    }

    def setup_method(self):
        args = {"owner": "airflow", "start_date": DEFAULT_DATE}
        self.dag = DAG("test_dag_id", schedule=None, default_args=args)

    @mock.patch("airflow.providers.dingding.operators.dingding.DingdingHook")
    def test_execute(self, mock_hook):
        operator = DingdingOperator(task_id="dingding_task", dag=self.dag, **self._config)

        assert operator is not None
        assert self._config["dingding_conn_id"] == operator.dingding_conn_id
        assert self._config["message_type"] == operator.message_type
        assert self._config["message"] == operator.message
        assert self._config["at_mobiles"] == operator.at_mobiles
        assert self._config["at_all"] == operator.at_all

        operator.execute(None)
        mock_hook.assert_called_once_with(
            self._config["dingding_conn_id"],
            self._config["message_type"],
            self._config["message"],
            self._config["at_mobiles"],
            self._config["at_all"],
        )
        mock_hook.return_value.send.assert_called_once_with()
