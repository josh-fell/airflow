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
"""Connect to Asana."""

from __future__ import annotations

from functools import cached_property
from typing import Any

from asana.api.projects_api import ProjectsApi
from asana.api.tasks_api import TasksApi
from asana.api_client import ApiClient
from asana.configuration import Configuration
from asana.rest import ApiException

try:
    from airflow.sdk import BaseHook
except ImportError:
    from airflow.hooks.base import BaseHook  # type: ignore[attr-defined,no-redef]


class AsanaHook(BaseHook):
    """Wrapper around Asana Python client library."""

    conn_name_attr = "asana_conn_id"
    default_conn_name = "asana_default"
    conn_type = "asana"
    hook_name = "Asana"

    def __init__(self, conn_id: str = default_conn_name, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.connection = self.get_connection(conn_id)
        extras = self.connection.extra_dejson
        self.workspace = self._get_field(extras, "workspace") or None
        self.project = self._get_field(extras, "project") or None

    def _get_field(self, extras: dict, field_name: str):
        """Get field from extra, first checking short name, then for backcompat we check for prefixed name."""
        backcompat_prefix = "extra__asana__"
        if field_name.startswith("extra__"):
            raise ValueError(
                f"Got prefixed name {field_name}; please remove the '{backcompat_prefix}' prefix "
                "when using this method."
            )
        if field_name in extras:
            return extras[field_name] or None
        prefixed_name = f"{backcompat_prefix}{field_name}"
        return extras.get(prefixed_name) or None

    def get_conn(self) -> ApiClient:
        return self.client

    @classmethod
    def get_connection_form_widgets(cls) -> dict[str, Any]:
        """Return connection widgets to add to connection form."""
        from flask_appbuilder.fieldwidgets import BS3TextFieldWidget
        from flask_babel import lazy_gettext
        from wtforms import StringField

        return {
            "workspace": StringField(lazy_gettext("Workspace"), widget=BS3TextFieldWidget()),
            "project": StringField(lazy_gettext("Project"), widget=BS3TextFieldWidget()),
        }

    @classmethod
    def get_ui_field_behaviour(cls) -> dict[str, Any]:
        """Return custom field behaviour."""
        return {
            "hidden_fields": ["port", "host", "login", "schema"],
            "relabeling": {},
            "placeholders": {
                "password": "Asana personal access token",
                "workspace": "Asana workspace gid",
                "project": "Asana project gid",
            },
        }

    @cached_property
    def client(self) -> ApiClient:
        """Instantiate python-asana Client."""
        if not self.connection.password:
            raise ValueError(
                "Asana connection password must contain a personal access token: "
                "https://developers.asana.com/docs/personal-access-token"
            )

        configuration = Configuration()
        configuration.access_token = self.connection.password
        return ApiClient(configuration)

    def create_task(self, task_name: str, params: dict | None) -> dict:
        """
        Create an Asana task.

        :param task_name: Name of the new task
        :param params: Other task attributes, such as due_on, parent, and notes. For a complete list
            of possible parameters, see https://developers.asana.com/docs/create-a-task
        :return: A dict of attributes of the created task, including its gid
        """
        merged_params = self._merge_create_task_parameters(task_name, params)
        self._validate_create_task_parameters(merged_params)

        tasks_api_instance = TasksApi(self.client)
        try:
            body = {"data": merged_params}
            response = tasks_api_instance.create_task(body, opts={})
            return response
        except ApiException as e:
            self.log.exception("Exception when calling create task with task name: %s", task_name)
            raise e

    def _merge_create_task_parameters(self, task_name: str, task_params: dict | None) -> dict:
        """
        Merge create_task parameters with default params from the connection.

        :param task_name: Name of the task
        :param task_params: Other task parameters which should override defaults from the connection
        :return: A dict of merged parameters to use in the new task
        """
        merged_params: dict[str, Any] = {"name": task_name}
        if self.project:
            merged_params["projects"] = [self.project]
        # Only use default workspace if user did not provide a project id
        elif self.workspace and not (task_params and ("projects" in task_params)):
            merged_params["workspace"] = self.workspace
        if task_params:
            merged_params.update(task_params)
        return merged_params

    @staticmethod
    def _validate_create_task_parameters(params: dict) -> None:
        """
        Check that user provided minimal parameters for task creation.

        :param params: A dict of attributes the task to be created should have
        :return: None; raises ValueError if `params` doesn't contain required parameters
        """
        required_parameters = {"workspace", "projects", "parent"}
        if required_parameters.isdisjoint(params):
            raise ValueError(
                f"You must specify at least one of {required_parameters} in the create_task parameters"
            )

    def delete_task(self, task_id: str) -> dict:
        """
        Delete an Asana task.

        :param task_id: Asana GID of the task to delete
        :return: A dict containing the response from Asana
        """
        tasks_api_instance = TasksApi(self.client)
        try:
            response = tasks_api_instance.delete_task(task_id)
            return response
        except ApiException as e:
            self.log.exception("Exception when calling delete task with task id: %s", task_id)
            raise e

    def find_task(self, params: dict | None) -> list:
        """
        Retrieve a list of Asana tasks that match search parameters.

        :param params: Attributes that matching tasks should have. For a list of possible parameters,
            see https://developers.asana.com/docs/get-multiple-tasks
        :return: A list of dicts containing attributes of matching Asana tasks
        """
        merged_params = self._merge_find_task_parameters(params)
        self._validate_find_task_parameters(merged_params)

        tasks_api_instance = TasksApi(self.client)
        try:
            response = tasks_api_instance.get_tasks(merged_params)
            return list(response)
        except ApiException as e:
            self.log.exception("Exception when calling find task with parameters: %s", params)
            raise e

    def _merge_find_task_parameters(self, search_parameters: dict | None) -> dict:
        """
        Merge find_task parameters with default params from the connection.

        :param search_parameters: Attributes that tasks matching the search should have; these override
            defaults from the connection
        :return: A dict of merged parameters to use in the search
        """
        merged_params = {}
        if self.project:
            merged_params["project"] = self.project
        # Only use default workspace if user did not provide a project id
        elif self.workspace and not (search_parameters and ("project" in search_parameters)):
            merged_params["workspace"] = self.workspace
        if search_parameters:
            merged_params.update(search_parameters)
        return merged_params

    @staticmethod
    def _validate_find_task_parameters(params: dict) -> None:
        """
        Check that the user provided minimal search parameters.

        :param params: Dict of parameters to be used in the search
        :return: None; raises ValueError if search parameters do not contain minimum required attributes
        """
        one_of_list = {"project", "section", "tag", "user_task_list"}
        both_of_list = {"assignee", "workspace"}
        contains_both = both_of_list.issubset(params)
        contains_one = not one_of_list.isdisjoint(params)
        if not (contains_both or contains_one):
            raise ValueError(
                f"You must specify at least one of {one_of_list} "
                f"or both of {both_of_list} in the find_task parameters."
            )

    def update_task(self, task_id: str, params: dict) -> dict:
        """
        Update an existing Asana task.

        :param task_id: Asana GID of task to update
        :param params: New values of the task's attributes. For a list of possible parameters, see
            https://developers.asana.com/docs/update-a-task
        :return: A dict containing the updated task's attributes
        """
        tasks_api_instance = TasksApi(self.client)
        try:
            body = {"data": params}
            response = tasks_api_instance.update_task(body, task_id, opts={})
            return response
        except ApiException as e:
            self.log.exception("Exception when calling update task with task id: %s", task_id)
            raise e

    def create_project(self, params: dict) -> dict:
        """
        Create a new project.

        :param params: Attributes that the new project should have. See
            https://developers.asana.com/docs/create-a-project#create-a-project-parameters
            for a list of possible parameters.
        :return: A dict containing the new project's attributes, including its GID.
        """
        merged_params = self._merge_project_parameters(params)
        self._validate_create_project_parameters(merged_params)

        projects_api_instance = ProjectsApi(self.client)
        try:
            body = {"data": merged_params}
            response = projects_api_instance.create_project(body)
            return response
        except ApiException as e:
            self.log.exception("Exception when calling create project with parameters: %s", merged_params)
            raise e

    @staticmethod
    def _validate_create_project_parameters(params: dict) -> None:
        """
        Check that user provided the minimum required parameters for project creation.

        :param params: Attributes that the new project should have
        :return: None; raises a ValueError if `params` does not contain the minimum required attributes.
        """
        required_parameters = {"workspace", "team"}
        if required_parameters.isdisjoint(params):
            raise ValueError(
                f"You must specify at least one of {required_parameters} in the create_project params"
            )

    def _merge_project_parameters(self, params: dict) -> dict:
        """
        Merge parameters passed into a project method with default params from the connection.

        :param params: Parameters passed into one of the project methods, which should override
            defaults from the connection
        :return: A dict of merged parameters
        """
        merged_params = {} if self.workspace is None else {"workspace": self.workspace}
        merged_params.update(params)
        return merged_params

    def find_project(self, params: dict) -> list:
        """
        Retrieve a list of Asana projects that match search parameters.

        :param params: Attributes which matching projects should have. See
            https://developers.asana.com/docs/get-multiple-projects
            for a list of possible parameters.
        :return: A list of dicts containing attributes of matching Asana projects
        """
        merged_params = self._merge_project_parameters(params)

        projects_api_instance = ProjectsApi(self.client)
        try:
            response = projects_api_instance.get_projects(merged_params)
            return list(response)
        except ApiException as e:
            self.log.exception("Exception when calling find projects with parameters: %s", params)
            raise e

    def update_project(self, project_id: str, params: dict) -> dict:
        """
        Update an existing project.

        :param project_id: Asana GID of the project to update
        :param params: New attributes that the project should have. See
            https://developers.asana.com/docs/update-a-project#update-a-project-parameters
            for a list of possible parameters
        :return: A dict containing the updated project's attributes
        """
        body = {"data": params}
        projects_api_instance = ProjectsApi(self.client)
        try:
            response = projects_api_instance.update_project(body, project_id)
            return response
        except ApiException as e:
            self.log.exception("Exception when calling project update with parameter: %s", params)
            raise e

    def delete_project(self, project_id: str) -> dict:
        """
        Delete a project.

        :param project_id: Asana GID of the project to delete
        :return: A dict containing the response from Asana
        """
        projects_api_instance = ProjectsApi(self.client)
        try:
            response = projects_api_instance.delete_project(project_id)
            return response
        except ApiException as e:
            self.log.exception("Exception when calling project delete with project id: %s", project_id)
            raise e
