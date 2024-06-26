#!/usr/bin/env python
"""
Generated by 'esmerald createproject'
"""

import os
import sys
from pathlib import Path

from esmerald import Esmerald, Include

import edgy
from edgy import Database, EdgyExtra, Registry

database = Database("sqlite:///db.sqlite")
registry = Registry(database)


class CustomModel(edgy.Model):
    name: str = edgy.CharField(max_length=255)
    email: str = edgy.EmailField(max_length=255)

    class Meta:
        registry = registry


def build_path():
    """
    Builds the path of the project and project root.
    """
    Path(__file__).resolve().parent.parent
    SITE_ROOT = os.path.dirname(os.path.realpath(__file__))

    if SITE_ROOT not in sys.path:
        sys.path.append(SITE_ROOT)
        sys.path.append(os.path.join(SITE_ROOT, "apps"))


def get_application():
    """
    This is optional. The function is only used for organisation purposes.
    """

    app = Esmerald(
        routes=[Include(namespace="my_project.urls")],
    )

    EdgyExtra(app=app, registry=registry)
    return app


app = get_application()
