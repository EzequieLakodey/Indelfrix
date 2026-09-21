#!/bin/bash
cd "$(dirname "$0")"
exec .venv/bin/python app.py >> /tmp/flask.log 2>&1
