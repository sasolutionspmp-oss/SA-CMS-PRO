"""Deliberately permissive pure test scaffold; never imported by the driver.

Run ``python test_guards.py --red-scaffold`` to retain the fail-first evidence.
This module is not an authority, runtime simulator, or production baseline.
"""
import datetime
import json


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def private_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def admit(lease_path, request_path, *, execute=False):
    return {"lease": private_json(lease_path), "request": private_json(request_path)}


def recheck(admission):
    return admission


def can_start(journal):
    return True
