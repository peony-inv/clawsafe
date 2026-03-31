"""
ClawSafe Default Rules — v0.1

These 20 rules cover the most common catastrophic agent actions.
Rules are evaluated in order. First non-None result wins.

WRITING YOUR OWN RULES:
    def my_rule(tool: str, args: dict) -> Decision | None:
        if tool != "my_tool": return None
        if something_dangerous(args):
            return Decision.block("reason", "rule_name")
        return None

Add your rule to a file at ~/.clawsafe/rules/myrule.py
Define either:
    - A list named RULES containing rule functions
    - A single function named `rule`
ClawSafe will auto-discover and load it on startup.
"""

from .models import Decision


# ─── TOOL SETS ────────────────────────────────────────────────────────────────

DELETE_TOOLS = {
    "gmail_delete", "email_delete", "mail_delete",
    "file_delete", "files_delete", "delete_file",
    "message_delete", "messages_delete",
    "calendar_delete", "event_delete",
    "contact_delete", "contacts_delete",
    "note_delete", "notes_delete",
    "document_delete", "doc_delete",
    "drive_delete", "gdrive_delete",
    "slack_delete", "discord_delete",
    "tweet_delete", "post_delete",
}

SEND_TOOLS = {
    "send_message", "send_email", "send_mail",
    "imessage_send", "sms_send", "mms_send",
    "slack_send", "slack_message",
    "discord_send", "discord_message",
    "gmail_send", "mail_send", "email_send",
    "whatsapp_send", "telegram_send",
    "tweet", "post_tweet",
    "linkedin_post", "facebook_post",
}

SHELL_TOOLS = {
    "exec", "execute", "shell_exec", "shell",
    "bash", "sh", "zsh", "fish",
    "run_command", "run_script", "terminal",
    "subprocess", "os_exec", "system",
    "powershell", "cmd",
}

PAYMENT_TOOLS = {
    "purchase", "buy", "pay", "payment",
    "checkout", "stripe_charge", "stripe_payment",
    "order", "place_order", "subscribe",
    "add_payment", "charge",
}

PUBLIC_POST_TOOLS = {
    "tweet", "post_tweet", "retweet",
    "linkedin_post", "facebook_post",
    "instagram_post", "tiktok_post",
    "blog_post", "publish", "publish_post",
    "medium_post", "substack_send",
}

MOVE_TOOLS = {
    "file_move", "file_copy", "mv", "cp",
    "move_file", "copy_file",
}

CALENDAR_WRITE_TOOLS = {
    "calendar_delete", "event_delete",
    "calendar_cancel", "event_cancel",
}

EXPORT_TOOLS = {
    "export_contacts", "contacts_export", "download_contacts",
    "export_emails", "email_export", "backup",
    "export_data", "data_export",
}

PERMISSION_TOOLS = {
    "grant_permission", "add_permission", "share",
    "make_public", "change_permissions",
    "oauth_grant", "add_collaborator",
}


# ─── RULE 1: Bulk Delete ──────────────────────────────────────────────────────
def bulk_delete_rule(tool: str, args: dict) -> Decision | None:
    """Block deletion of more than 10 items at once (Summer Yue scenario)."""
    if tool not in DELETE_TOOLS:
        return None

    ids = (
        args.get("ids") or
        args.get("message_ids") or
        args.get("file_ids") or
        args.get("event_ids") or
        args.get("contact_ids") or
        args.get("document_ids") or
        []
    )

    if isinstance(ids, list) and len(ids) > 10:
        return Decision.block(
            reason=f"Bulk delete blocked: {len(ids)} items would be deleted. Limit is 10.",
            rule_name="bulk_delete"
        )

    return None


# ─── RULE 2: Query-Based Delete ───────────────────────────────────────────────
def query_delete_rule(tool: str, args: dict) -> Decision | None:
    """Block deletes triggered by a search query (unknown item count)."""
    if tool not in DELETE_TOOLS:
        return None

    query = (
        args.get("query") or
        args.get("filter") or
        args.get("search") or
        args.get("where") or
        args.get("criteria")
    )
    ids = (
        args.get("ids") or
        args.get("message_ids") or
        args.get("file_ids") or
        []
    )

    if query and not ids:
        return Decision.block(
            reason=f"Query-based delete blocked: unknown number of items match query '{query}'.",
            rule_name="query_delete"
        )

    return None


# ─── RULE 3: Bulk Send (BLOCK) ────────────────────────────────────────────────
def bulk_send_block_rule(tool: str, args: dict) -> Decision | None:
    """Block sends to more than 5 recipients (Chris Boyd scenario)."""
    if tool not in SEND_TOOLS:
        return None

    recipients = (
        args.get("recipients") or
        args.get("to") or
        args.get("contacts") or
        args.get("addresses") or
        []
    )

    if isinstance(recipients, str):
        recipients = [recipients]

    if len(recipients) > 5:
        return Decision.block(
            reason=f"Bulk send blocked: {len(recipients)} recipients exceeds limit of 5.",
            rule_name="bulk_send_block"
        )

    return None


# ─── RULE 4: Multi-Recipient Send (GRAY) ─────────────────────────────────────
def multi_recipient_send_gray_rule(tool: str, args: dict) -> Decision | None:
    """Escalate sends to 2-5 recipients for cloud AI verification."""
    if tool not in SEND_TOOLS:
        return None

    recipients = (
        args.get("recipients") or
        args.get("to") or
        args.get("contacts") or
        []
    )

    if isinstance(recipients, str):
        recipients = [recipients]

    if 2 <= len(recipients) <= 5:
        return Decision.gray(
            reason=f"Sending to {len(recipients)} recipients — verifying intent.",
            rule_name="multi_recipient_gray"
        )

    return None


# ─── RULE 5: Shell Execution ──────────────────────────────────────────────────
def shell_exec_rule(tool: str, args: dict) -> Decision | None:
    """Block shell command execution entirely (config override in engine.py)."""
    if tool in SHELL_TOOLS:
        return Decision.block(
            reason=(
                "Shell execution blocked by default. "
                "To allow, set rules.allow_shell_exec: true in ~/.clawsafe/config.yaml"
            ),
            rule_name="shell_exec"
        )

    return None


# ─── RULE 6: Recursive File Operations ────────────────────────────────────────
def recursive_file_rule(tool: str, args: dict) -> Decision | None:
    """Block recursive file operations (rm -rf style)."""
    if tool not in (DELETE_TOOLS | MOVE_TOOLS):
        return None

    if args.get("recursive") is True or args.get("recursive") == "true":
        return Decision.block(
            reason="Recursive file operation blocked. Operations affecting entire directory trees require manual confirmation.",
            rule_name="recursive_file"
        )

    return None


# ─── RULE 7: Payment / Purchase ───────────────────────────────────────────────
def payment_rule(tool: str, args: dict) -> Decision | None:
    """Block all payment and purchase actions."""
    if tool in PAYMENT_TOOLS:
        amount = args.get("amount") or args.get("price") or "unknown amount"
        return Decision.block(
            reason=f"Payment blocked: ${amount}. AI agents are not permitted to make purchases autonomously.",
            rule_name="payment"
        )

    return None


# ─── RULE 8: Public Post ──────────────────────────────────────────────────────
def public_post_rule(tool: str, args: dict) -> Decision | None:
    """Block all public-facing posts."""
    if tool in PUBLIC_POST_TOOLS:
        return Decision.block(
            reason="Public post blocked: posting publicly requires human confirmation.",
            rule_name="public_post"
        )

    return None


# ─── RULE 9: File Write Outside Home Directory (GRAY) ─────────────────────────
def outside_home_write_gray_rule(tool: str, args: dict) -> Decision | None:
    """Escalate file writes outside the user's home directory."""
    import os

    WRITE_TOOLS = {"file_write", "file_create", "write_file", "create_file", "save_file"}

    if tool not in WRITE_TOOLS:
        return None

    path = (
        args.get("path") or
        args.get("file_path") or
        args.get("destination") or
        ""
    )

    if not path:
        return None

    home = os.path.expanduser("~")
    abs_path = os.path.abspath(path)

    if not abs_path.startswith(home):
        return Decision.gray(
            reason=f"Writing outside home directory: '{path}'. Verifying intent.",
            rule_name="outside_home_write"
        )

    return None


# ─── RULE 10: Large File Delete ───────────────────────────────────────────────
def large_file_delete_rule(tool: str, args: dict) -> Decision | None:
    """Block deletion of files larger than 100MB."""
    if tool not in DELETE_TOOLS:
        return None

    size_bytes = args.get("size_bytes") or args.get("size") or 0

    if isinstance(size_bytes, (int, float)) and size_bytes > 100_000_000:
        size_mb = size_bytes / 1_000_000
        return Decision.block(
            reason=f"Large file delete blocked: file is {size_mb:.1f}MB (limit: 100MB).",
            rule_name="large_file_delete"
        )

    return None


# ─── RULE 11: Contact Export ──────────────────────────────────────────────────
def contact_export_rule(tool: str, args: dict) -> Decision | None:
    """Block exporting contact lists."""
    if tool in EXPORT_TOOLS:
        scope = args.get("scope") or args.get("type") or "data"
        return Decision.block(
            reason=f"Data export blocked: exporting '{scope}' requires human confirmation.",
            rule_name="contact_export"
        )

    return None


# ─── RULE 12: Bulk Calendar Delete ────────────────────────────────────────────
def bulk_calendar_delete_rule(tool: str, args: dict) -> Decision | None:
    """Block bulk deletion of calendar events."""
    if tool not in CALENDAR_WRITE_TOOLS:
        return None

    event_ids = (
        args.get("event_ids") or
        args.get("ids") or
        []
    )

    if isinstance(event_ids, list) and len(event_ids) > 3:
        return Decision.block(
            reason=f"Bulk calendar delete blocked: {len(event_ids)} events. Limit is 3.",
            rule_name="bulk_calendar_delete"
        )

    if args.get("all") is True or args.get("query") == "*" or args.get("range") == "all":
        return Decision.block(
            reason="Mass calendar cancellation blocked. This would delete all events.",
            rule_name="bulk_calendar_delete_all"
        )

    return None


# ─── RULE 13: Permission Escalation ───────────────────────────────────────────
def permission_escalation_rule(tool: str, args: dict) -> Decision | None:
    """Block granting new permissions to third parties."""
    if tool in PERMISSION_TOOLS:
        target = args.get("target") or args.get("grantee") or args.get("user") or "unknown"
        return Decision.block(
            reason=f"Permission grant blocked: granting access to '{target}' requires human confirmation.",
            rule_name="permission_escalation"
        )

    return None


# ─── RULE 14: Unsubscribe / Account Deletion ──────────────────────────────────
def account_action_rule(tool: str, args: dict) -> Decision | None:
    """Block account deletion and subscription cancellation."""
    ACCOUNT_TOOLS = {
        "delete_account", "account_delete", "close_account",
        "cancel_subscription", "unsubscribe", "deactivate",
        "delete_user", "remove_account",
    }

    if tool in ACCOUNT_TOOLS:
        return Decision.block(
            reason="Account action blocked: deleting accounts or cancelling subscriptions requires human confirmation.",
            rule_name="account_action"
        )

    return None


# ─── RULE 15: Email Filter / Rule Creation ────────────────────────────────────
def email_rule_creation_rule(tool: str, args: dict) -> Decision | None:
    """Flag creating email filters that auto-delete or auto-archive."""
    EMAIL_FILTER_TOOLS = {
        "create_filter", "gmail_filter", "email_filter",
        "create_rule", "email_rule", "mail_rule",
    }

    if tool not in EMAIL_FILTER_TOOLS:
        return None

    action = str(args.get("action") or args.get("then") or "").lower()

    if "delete" in action or "trash" in action or "archive" in action:
        return Decision.gray(
            reason=f"Email filter with destructive action ('{action}') — verifying intent.",
            rule_name="email_rule_destructive"
        )

    return None


# ─── RULE 16: Forwarding Rules ────────────────────────────────────────────────
def email_forwarding_rule(tool: str, args: dict) -> Decision | None:
    """Block setting up email forwarding to external addresses."""
    FORWARD_TOOLS = {
        "create_forwarding", "add_forwarding", "set_forwarding",
        "email_forward", "forward_email", "gmail_forward",
    }

    if tool in FORWARD_TOOLS:
        forward_to = args.get("forward_to") or args.get("to") or args.get("address") or "unknown"
        return Decision.block(
            reason=f"Email forwarding blocked: setting up forwarding to '{forward_to}' requires human confirmation.",
            rule_name="email_forwarding"
        )

    return None


# ─── RULE 17: Script / Automation Creation ────────────────────────────────────
def automation_creation_rule(tool: str, args: dict) -> Decision | None:
    """Block creating new automations or scheduled tasks."""
    AUTOMATION_TOOLS = {
        "create_automation", "create_workflow", "create_cron",
        "schedule_task", "create_trigger", "add_webhook",
        "create_zapier", "create_n8n", "register_hook",
    }

    if tool in AUTOMATION_TOOLS:
        return Decision.gray(
            reason="Creating a new automation — verifying this is intentional.",
            rule_name="automation_creation"
        )

    return None


# ─── RULE 18: Bulk Archive ────────────────────────────────────────────────────
def bulk_archive_rule(tool: str, args: dict) -> Decision | None:
    """Gray-area for bulk archive operations."""
    ARCHIVE_TOOLS = {
        "gmail_archive", "email_archive", "archive_emails",
        "archive_messages", "archive_all",
    }

    if tool not in ARCHIVE_TOOLS:
        return None

    ids = args.get("ids") or args.get("message_ids") or []
    query = args.get("query") or ""

    if (isinstance(ids, list) and len(ids) > 50) or (query and not ids):
        return Decision.gray(
            reason="Large archive operation — verifying intent.",
            rule_name="bulk_archive"
        )

    return None


# ─── RULE 19: Sensitive File Access (GRAY) ────────────────────────────────────
def sensitive_file_read_rule(tool: str, args: dict) -> Decision | None:
    """Flag reads of sensitive files (SSH keys, env files, credential files)."""
    import re

    READ_TOOLS = {"file_read", "read_file", "open_file", "cat", "get_file"}

    SENSITIVE_PATTERNS = [
        r"\.ssh/", r"id_rsa", r"id_ed25519",
        r"\.env$", r"\.env\.",
        r"\.pem$", r"\.key$", r"\.p12$",
        r"password", r"credential", r"secret",
        r"_token", r"api_key",
        r"\.netrc$", r"\.aws/credentials",
    ]

    if tool not in READ_TOOLS:
        return None

    path = (
        args.get("path") or
        args.get("file_path") or
        args.get("filename") or
        ""
    ).lower()

    for pattern in SENSITIVE_PATTERNS:
        if re.search(pattern, path, re.IGNORECASE):
            return Decision.gray(
                reason=f"Reading potentially sensitive file: '{path}'. Verifying intent.",
                rule_name="sensitive_file_read"
            )

    return None


# ─── RULE 20: Unknown Tool Passthrough (LOG ONLY) ─────────────────────────────
def unknown_tool_log_rule(tool: str, args: dict) -> Decision | None:
    """Default: allow unknown tools through. Return None = no opinion."""
    return None


# ─── THE ORDERED LIST ─────────────────────────────────────────────────────────

DEFAULT_RULES = [
    bulk_delete_rule,               # 1. Block bulk delete (>10 items)
    query_delete_rule,              # 2. Block query-based delete
    bulk_send_block_rule,           # 3. Block bulk send (>5 recipients)
    multi_recipient_send_gray_rule, # 4. Gray multi-recipient (2-5)
    shell_exec_rule,                # 5. Block shell execution
    recursive_file_rule,            # 6. Block recursive file ops
    payment_rule,                   # 7. Block all payments
    public_post_rule,               # 8. Block public posts
    outside_home_write_gray_rule,   # 9. Gray writes outside home dir
    large_file_delete_rule,         # 10. Block large file delete
    contact_export_rule,            # 11. Block data exports
    bulk_calendar_delete_rule,      # 12. Block bulk calendar delete
    permission_escalation_rule,     # 13. Block permission grants
    account_action_rule,            # 14. Block account deletion
    email_rule_creation_rule,       # 15. Gray destructive email filters
    email_forwarding_rule,          # 16. Block forwarding rules
    automation_creation_rule,       # 17. Gray new automation creation
    bulk_archive_rule,              # 18. Gray bulk archive
    sensitive_file_read_rule,       # 19. Gray sensitive file reads
    unknown_tool_log_rule,          # 20. Default: allow (no-op)
]
