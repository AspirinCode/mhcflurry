# Copyright (c) 2016. Mount Sinai School of Medicine
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Manage local downloaded data.
"""

from __future__ import (
    print_function,
    division,
    absolute_import,
)
import logging
import yaml
from os.path import join, exists
from pipes import quote
from os import environ
from collections import OrderedDict
from appdirs import user_data_dir
from pkg_resources import resource_string

ENVIRONMENT_VARIABLES = [
    "MHCFLURRY_DATA_DIR",
    "MHCFLURRY_DOWNLOADS_CURRENT_RELEASE",
    "MHCFLURRY_DOWNLOADS_DIR",
]

_DOWNLOADS_DIR = None
_CURRENT_RELEASE = None
_METADATA = None


def get_downloads_dir():
    """
    Return the path to local downloaded data
    """
    return _DOWNLOADS_DIR


def get_current_release():
    """
    Return the current downloaded data release
    """
    return _CURRENT_RELEASE


def get_downloads_metadata():
    """
    Return the contents of downloads.yml as a dict
    """
    global _METADATA
    if _METADATA is None:
        _METADATA = yaml.load(resource_string(__name__, "downloads.yml"))
    return _METADATA


def get_current_release_downloads():
    """
    Return a dict of all available downloads in the current release.

    The dict keys are the names of the downloads. The values are a dict
    with two entries:

    downloaded : bool
        Whether the download is currently available locally

    metadata : dict
        Info about the download from downloads.yml such as URL
    """
    downloads = (
        get_downloads_metadata()
        ['releases']
        [get_current_release()]
        ['downloads'])
    return OrderedDict(
        (download["name"], {
            'downloaded': exists(join(get_downloads_dir(), download["name"])),
            'metadata': download,
        }) for download in downloads
    )


def get_path(download_name, filename='', test_exists=True):
    """
    Get the local path to a file in a MHCflurry download

    Parameters
    -----------
    download_name : string

    filename : string
        Relative path within the download to the file of interest

    test_exists : boolean
        If True (default) throw an error telling the user how to download the
        data if the file does not exist

    Returns
    -----------
    string giving local absolute path
    """
    assert '/' not in download_name, "Invalid download: %s" % download_name
    path = join(get_downloads_dir(), download_name, filename)
    if test_exists and not exists(path):
        raise RuntimeError(
            "Missing MHCflurry downloadable file: %s. "
            "To download this data, run:\n\tmhcflurry-downloads fetch %s\n"
            "in a shell."
            % (quote(path), download_name))
    return path


def configure():
    """
    Setup various global variables based on environment variables.
    """
    global _DOWNLOADS_DIR
    global _CURRENT_RELEASE

    _CURRENT_RELEASE = None
    _DOWNLOADS_DIR = environ.get("MHCFLURRY_DOWNLOADS_DIR")
    if not _DOWNLOADS_DIR:
        metadata = get_downloads_metadata()
        _CURRENT_RELEASE = environ.get("MHCFLURRY_DOWNLOADS_CURRENT_RELEASE")
        if not _CURRENT_RELEASE:
            _CURRENT_RELEASE = metadata['current-release']

        current_release_compatability = (
            metadata["releases"][_CURRENT_RELEASE]["compatibility-version"])
        current_compatability = metadata["current-compatibility-version"]
        if current_release_compatability != current_compatability:
            logging.warn(
                "The specified downloads are not compatible with this version "
                "of the MHCflurry codebase. Downloads: release %s, "
                "compatability version: %d. Code compatability version: %d" % (
                    _CURRENT_RELEASE,
                    current_release_compatability,
                    current_compatability))

        data_dir = environ.get("MHCFLURRY_DATA_DIR")
        if not data_dir:
            # increase the version every time we make a breaking change in
            # how the data is organized. For changes to e.g. just model
            # serialization, the downloads release numbers should be used.
            data_dir = user_data_dir("mhcflurry", version="4")
        _DOWNLOADS_DIR = join(data_dir, _CURRENT_RELEASE)

    logging.debug("Configured MHCFLURRY_DOWNLOADS_DIR: %s" % _DOWNLOADS_DIR)

configure()
