"""stream_console_routes.py — Additive /stream-console route (dev, not compiled).

The deployed app runs from pymod/*.pyc, so source app.py edits are not picked
up. Following the bible.py / live_input.py pattern, this registers the stream
console page on the already-existing Flask app at boot via init_app().
"""


def init_app(app):
    """Register the Stream Console page route (additive)."""
    from flask import render_template

    @app.route("/stream-console")
    def stream_console_route():
        return render_template("stream_console.html", channel="ch1")