"""Tests for the portal core."""
from lib import base

CORE = "portal"


class Static(base.StaticChecks):
    core = CORE


class Load(base.LoadChecks):
    core = CORE


class Visibility(base.CommitVisibility):
    core = CORE


class Generic(base.GenericLive):
    core = CORE
