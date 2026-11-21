"""Account blueprint — /api/account: the Discord sign-in the backend holds (shared/account/).
Settings > Files & setup > Account signs in and out here and the Upload tab reads the account as a
publishing identity. Not gated: publishing and bug reports use it."""

from flask import Blueprint, jsonify

from shared.account import discord

account_bp = Blueprint("account", __name__, url_prefix="/api/account")


def _discord_state():
    return {"account": discord.account_summary(), "auth": discord.auth_status()}


@account_bp.route("/discord", methods=["GET"])
def get_discord():
    """{account: {user_id, username, discord_username, avatar_url, source: "discord"} | null,
    auth: {state: idle|pending|done|error, error}}"""
    return jsonify(_discord_state())


@account_bp.route("/discord/start", methods=["POST"])
def post_discord_start():
    """Opens the Discord sign-in in the browser -> {url, account, auth}; poll GET while
    auth.state is pending."""
    try:
        url = discord.start_sign_in()
    except discord.SignInUnavailable as e:
        return jsonify({"success": False, "error": str(e), **_discord_state()}), 409
    return jsonify({"url": url, **_discord_state()})


@account_bp.route("/discord/signout", methods=["POST"])
def post_discord_signout():
    discord.sign_out()
    return jsonify(_discord_state())
