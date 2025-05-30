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

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, TextIO

from airflow_breeze.utils.console import get_console
from airflow_breeze.utils.packages import (
    get_available_distributions,
    get_latest_provider_tag,
    get_not_ready_provider_ids,
    get_provider_details,
    get_provider_jinja_context,
    get_removed_provider_ids,
    regenerate_pyproject_toml,
    render_template,
    tag_exists_for_provider,
)
from airflow_breeze.utils.run_utils import run_command
from airflow_breeze.utils.version_utils import is_local_package_version

LICENCE_RST = """
.. Licensed to the Apache Software Foundation (ASF) under one
   or more contributor license agreements.  See the NOTICE file
   distributed with this work for additional information
   regarding copyright ownership.  The ASF licenses this file
   to you under the Apache License, Version 2.0 (the
   "License"); you may not use this file except in compliance
   with the License.  You may obtain a copy of the License at

..   http://www.apache.org/licenses/LICENSE-2.0

.. Unless required by applicable law or agreed to in writing,
   software distributed under the License is distributed on an
   "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
   KIND, either express or implied.  See the License for the
   specific language governing permissions and limitations
   under the License.
"""


class PrepareReleasePackageTagExistException(Exception):
    """Tag already exist for the package."""


class PrepareReleasePackageWrongSetupException(Exception):
    """Wrong setup prepared for the package."""


class PrepareReleasePackageErrorBuildingPackageException(Exception):
    """Error when building the package."""


def get_provider_distribution_jinja_context(provider_id: str, version_suffix: str) -> dict[str, Any]:
    provider_details = get_provider_details(provider_id)
    jinja_context = get_provider_jinja_context(
        provider_id=provider_id,
        current_release_version=provider_details.versions[0],
        version_suffix=version_suffix,
    )
    return jinja_context


def _prepare_get_provider_info_py_file(context: dict[str, Any], provider_id: str, target_path: Path):
    from airflow_breeze.utils.black_utils import black_format

    get_provider_template_name = "get_provider_info"
    get_provider_content = render_template(
        template_name=get_provider_template_name,
        context=context,
        extension=".py",
        autoescape=False,
        keep_trailing_newline=True,
    )
    target_provider_specific_path = (target_path / "airflow" / "providers").joinpath(*provider_id.split("."))
    (target_provider_specific_path / "get_provider_info.py").write_text(black_format(get_provider_content))
    get_console().print(f"[info]Generated get_provider_info.py in {target_provider_specific_path}[/]")


def _prepare_pyproject_toml_file(context: dict[str, Any], target_path: Path):
    manifest_content = render_template(
        template_name="pyproject",
        context=context,
        extension=".toml",
        autoescape=False,
        lstrip_blocks=True,
        trim_blocks=True,
        keep_trailing_newline=True,
    )
    (target_path / "pyproject.toml").write_text(manifest_content)
    get_console().print(f"[info]Generated pyproject.toml in {target_path}[/]")


def _prepare_readme_file(context: dict[str, Any], target_path: Path):
    readme_content = LICENCE_RST + render_template(
        template_name="PROVIDER_README", context=context, extension=".rst"
    )
    (target_path / "README.rst").write_text(readme_content)
    get_console().print(f"[info]Generated README.rst in {target_path}[/]")


def generate_build_files(provider_id: str, version_suffix: str, target_provider_root_sources_path: Path):
    get_console().print(f"\n[info]Generate build files for {provider_id}\n")
    jinja_context = get_provider_distribution_jinja_context(
        provider_id=provider_id, version_suffix=version_suffix
    )
    _prepare_get_provider_info_py_file(jinja_context, provider_id, target_provider_root_sources_path)
    _prepare_pyproject_toml_file(jinja_context, target_provider_root_sources_path)
    _prepare_readme_file(jinja_context, target_provider_root_sources_path)
    get_console().print(f"\n[info]Generated package build files for {provider_id}[/]\n")


def should_skip_the_package(provider_id: str, version_suffix: str) -> tuple[bool, str]:
    """Return True, version if the package should be skipped and False, good version suffix if not.

    For RC and official releases we check if the "officially released" version exists
    and skip the released if it was. This allows to skip packages that have not been
    marked for release in this wave. For "dev" suffixes, we always build all packages.
    A local version of an RC release will always be built.
    """
    if version_suffix != "" and (
        not version_suffix.startswith("rc") or is_local_package_version(version_suffix)
    ):
        return False, version_suffix
    if version_suffix == "":
        current_tag = get_latest_provider_tag(provider_id, "")
        if tag_exists_for_provider(provider_id, current_tag):
            get_console().print(f"[warning]The 'final' tag {current_tag} exists. Skipping the package.[/]")
            return True, version_suffix
        return False, version_suffix
    # version_suffix starts with "rc"
    current_version = int(version_suffix[2:])
    release_tag = get_latest_provider_tag(provider_id, "")
    if tag_exists_for_provider(provider_id, release_tag):
        get_console().print(f"[warning]The tag {release_tag} exists. Provider is released. Skipping it.[/]")
        return True, version_suffix
    while True:
        current_tag = get_latest_provider_tag(provider_id, f"rc{current_version}")
        if tag_exists_for_provider(provider_id, current_tag):
            current_version += 1
            get_console().print(f"[warning]The tag {current_tag} exists. Checking rc{current_version}.[/]")
        else:
            return False, f"rc{current_version}"


def cleanup_build_remnants(target_provider_root_sources_path: Path):
    get_console().print(f"\n[info]Cleaning remnants in {target_provider_root_sources_path}")
    for file in target_provider_root_sources_path.glob("*.egg-info"):
        shutil.rmtree(file, ignore_errors=True)
    shutil.rmtree(target_provider_root_sources_path / "build", ignore_errors=True)
    shutil.rmtree(target_provider_root_sources_path / "dist", ignore_errors=True)
    get_console().print(f"[info]Cleaned remnants in {target_provider_root_sources_path}\n")


def apply_version_suffix_to_pyproject_toml(
    provider_id: str, target_provider_root_sources_path: Path, version_suffix: str
) -> str:
    pyproject_toml_path = target_provider_root_sources_path / "pyproject.toml"
    original_pyproject_toml_content = pyproject_toml_path.read_text()
    if not version_suffix:
        return original_pyproject_toml_content
    get_console().print(f"\n[info]Applying version suffix {version_suffix} to {pyproject_toml_path}")
    jinja_context = get_provider_distribution_jinja_context(
        provider_id=provider_id, version_suffix=version_suffix
    )
    provider_details = get_provider_details(provider_id)
    regenerate_pyproject_toml(jinja_context, provider_details, version_suffix)
    _prepare_pyproject_toml_file(jinja_context, target_provider_root_sources_path)
    return original_pyproject_toml_content


def restore_pyproject_toml(target_provider_root_sources_path: Path, original_pyproject_toml_content: str):
    pyproject_toml_path = target_provider_root_sources_path / "pyproject.toml"
    get_console().print(f"\n[info]Restoring original pyproject.toml in {pyproject_toml_path}")
    pyproject_toml_path.write_text(original_pyproject_toml_content)


def build_provider_distribution(
    provider_id: str, target_provider_root_sources_path: Path, distribution_format: str
):
    get_console().print(
        f"\n[info]Building provider package: {provider_id} "
        f"in format {distribution_format} in {target_provider_root_sources_path}\n"
    )
    command: list[str] = [sys.executable, "-m", "flit", "build", "--no-setup-py", "--use-vcs"]
    get_console().print(
        "[warning]Workaround wheel-only package bug in flit by building both and removing sdist."
    )
    # Workaround https://github.com/pypa/flit/issues/743 bug in flit that causes .gitignored files
    # to be included in the package when --format wheel is used
    remove_sdist = False
    if distribution_format == "wheel":
        distribution_format = "both"
        remove_sdist = True
    if distribution_format != "both":
        command.extend(["--format", distribution_format])
    try:
        run_command(
            command,
            check=True,
            cwd=target_provider_root_sources_path,
            env={
                "SOURCE_DATE_EPOCH": str(get_provider_details(provider_id).source_date_epoch),
            },
        )
    except subprocess.CalledProcessError as ex:
        get_console().print("[error]The command returned an error %s", ex)
        raise PrepareReleasePackageErrorBuildingPackageException()
    if remove_sdist:
        get_console().print("[warning]Removing sdist file to workaround flit bug on wheel-only packages")
        # Remove the sdist file if it was created
        package_prefix = "apache_airflow_providers_" + provider_id.replace(".", "_")
        for file in (target_provider_root_sources_path / "dist").glob(f"{package_prefix}*.tar.gz"):
            get_console().print(f"[info]Removing {file} to workaround flit bug on wheel-only packages")
            file.unlink(missing_ok=True)
    get_console().print(
        f"\n[info]Prepared provider package {provider_id} in format {distribution_format}[/]\n"
    )


def move_built_distributions_and_cleanup(
    target_provider_root_sources_path: Path,
    dist_folder: Path,
    skip_cleanup: bool,
    delete_only_build_and_dist_folders: bool = False,
):
    for file in (target_provider_root_sources_path / "dist").glob("apache*"):
        get_console().print(f"[info]Moving {file} to {dist_folder}")
        # Shutil can move packages also between filesystems
        target_file = dist_folder / file.name
        target_file.unlink(missing_ok=True)
        shutil.move(file.as_posix(), dist_folder.as_posix())

    if skip_cleanup:
        get_console().print(
            f"[warning]NOT Cleaning up the {target_provider_root_sources_path} because "
            f"it was requested by the user[/]\n"
            f"\nYou can use the generated packages to work on the build"
            f"process and bring the changes back to the templates in Breeze "
            f"src/airflow_breeze/templates"
        )
    else:
        get_console().print(
            f"[info]Cleaning up {target_provider_root_sources_path} with "
            f"delete_only_build_and_dist_folders={delete_only_build_and_dist_folders}"
        )
        if delete_only_build_and_dist_folders:
            shutil.rmtree(target_provider_root_sources_path / "build", ignore_errors=True)
            shutil.rmtree(target_provider_root_sources_path / "dist", ignore_errors=True)
            for file in target_provider_root_sources_path.glob("*.egg-info"):
                shutil.rmtree(file, ignore_errors=True)
        else:
            shutil.rmtree(target_provider_root_sources_path, ignore_errors=True)
        get_console().print(f"[info]Cleaned up {target_provider_root_sources_path}")


def get_packages_list_to_act_on(
    distributions_list_file: TextIO | None,
    provider_distributions: tuple[str, ...],
    include_not_ready: bool = False,
    include_removed: bool = False,
) -> list[str]:
    if distributions_list_file and provider_distributions:
        get_console().print(
            "[error]You cannot specify individual provider distributions when you specify package list file."
        )
        sys.exit(1)
    if distributions_list_file:
        removed_provider_ids = get_removed_provider_ids()
        not_ready_provider_ids = get_not_ready_provider_ids()
        return [
            package.strip()
            for package in distributions_list_file.readlines()
            if not package.strip().startswith("#")
            and (package.strip() not in removed_provider_ids or include_removed)
            and (package.strip() not in not_ready_provider_ids or include_not_ready)
        ]
    if provider_distributions:
        return list(provider_distributions)
    return get_available_distributions(include_removed=include_removed, include_not_ready=include_not_ready)
