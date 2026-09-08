"""Test for the OBS-style Controls panel in the operator console.

Renders templates/index.html with a minimal program context and asserts that
the Controls panel markup, its active-state styling, and the obsActivate()
function are all present. Runs with a plain Python interpreter (no pytest).

Usage:
    python tests/test_controls_panel.py
"""

import os
import re
import sys

import flask


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TEMPLATE = os.path.join(REPO, 'templates', 'index.html')


def _render_index():
    app = flask.Flask(__name__, template_folder=os.path.join(REPO, 'templates'))
    from types import SimpleNamespace
    prog = SimpleNamespace(service_programs=[])
    ctx = app.test_request_context()
    ctx.push()
    try:
        return flask.render_template('index.html', program=prog, server_ip='127.0.0.1')
    finally:
        ctx.pop()


def _load_template_source():
    with open(TEMPLATE, 'r', encoding='utf-8') as fh:
        return fh.read()


def _check(label, cond):
    status = 'PASS' if cond else 'FAIL'
    print('  [%s] %s' % (status, label))
    return cond


def main():
    html = _render_index()
    src = _load_template_source()
    results = []

    print('Controls panel markup (rendered):')
    results.append(_check('obs-controls panel present', 'obs-controls' in html))
    results.append(_check('obs-header present', 'obs-header' in html))
    results.append(_check('obs-dock present', 'obs-dock' in html))
    results.append(_check('obs-body present', 'obs-body' in html))
    results.append(_check('gear button present', 'obs-gear' in html))

    obs = re.findall(r'data-obs="([a-z-]+)"', html)
    print('  data-obs values:', obs)
    results.append(_check('six action buttons wired', sorted(obs) == sorted([
        'send-custom', 'send-ann', 'live', 'blank', 'timer', 'screen',
    ])))

    print('Controls panel styling:')
    results.append(_check('.obs-btn active rule exists', '.obs-btn.active' in src))
    results.append(_check('active colour #2855c5 used', '#2855c5' in src))
    results.append(_check('button colour #444856 used', '#444856' in src))

    print('Active-state logic:')
    results.append(_check('obsActivate function defined', 'function obsActivate' in html))
    results.append(_check('obsActivate removes active from all', 'querySelectorAll(\'.obs-btn\')' in html))
    results.append(_check('obsActivate adds active to selected', 'classList.add(\'active\')' in html))

    # Each button triggers its real action handler too.
    results.append(_check('sendCustomOutput wired', 'sendCustomOutput()' in html))
    results.append(_check('sendAnnouncement wired', 'sendAnnouncement()' in html))
    results.append(_check('livePush wired', 'livePush()' in html))
    results.append(_check('_projBlank wired', '_projBlank()' in html))
    results.append(_check('timerStart wired', 'timerStart()' in html))
    results.append(_check('openScreenConfig wired', 'openScreenConfig()' in html))

    failed = results.count(False)
    print()
    if failed:
        print('RESULT: %d of %d checks FAILED' % (failed, len(results)))
        return 1
    print('RESULT: all %d checks PASSED' % len(results))
    return 0


if __name__ == '__main__':
    sys.exit(main())
