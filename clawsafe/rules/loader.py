"""
Rule loader — discovers and loads custom user rules from disk.

User rules live at:
  ~/.clawsafe/rules/*.py       — Python rule files
  ~/.clawsafe/rules/*.yaml     — YAML rule files (compiled to Python)
"""

from __future__ import annotations

import importlib.util
import logging
import re
from pathlib import Path

import yaml

from .models import Decision, RuleFunction

logger = logging.getLogger(__name__)


def load_user_rules(config_dir: Path) -> list[RuleFunction]:
    """Load all user-defined rules from ~/.clawsafe/rules/"""
    rules_dir = config_dir / "rules"

    if not rules_dir.exists():
        return []

    loaded = []

    for rule_file in sorted(rules_dir.glob("*.py")):
        rules = _load_python_file(rule_file)
        if rules:
            loaded.extend(rules)
            logger.info(f"Loaded {len(rules)} rule(s) from {rule_file.name}")

    for yaml_file in sorted(rules_dir.glob("*.yaml")):
        rule = _compile_yaml_rule(yaml_file)
        if rule:
            loaded.append(rule)
            logger.info(f"Loaded YAML rule from {yaml_file.name}")

    return loaded


def _load_python_file(rule_file: Path) -> list[RuleFunction]:
    """Load Python rule functions from a file."""
    try:
        spec = importlib.util.spec_from_file_location(
            f"clawsafe_rule_{rule_file.stem}", rule_file
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if hasattr(module, "RULES") and isinstance(module.RULES, list):
            return module.RULES
        elif hasattr(module, "rule") and callable(module.rule):
            return [module.rule]
        else:
            logger.warning(
                f"Rule file {rule_file.name} must define RULES (list) or rule (function). Skipping."
            )
            return []
    except Exception as e:
        logger.error(f"Failed to load rule file {rule_file.name}: {e}")
        return []


def _compile_yaml_rule(yaml_file: Path) -> RuleFunction | None:
    """Compile a YAML rule definition into a Python rule function."""
    try:
        with open(yaml_file) as f:
            rule_def = yaml.safe_load(f)

        if not rule_def:
            return None

        if not rule_def.get("enabled", True):
            logger.debug(f"YAML rule {yaml_file.name} is disabled, skipping")
            return None

        name = rule_def.get("name")
        if not name:
            logger.warning(f"YAML rule {yaml_file.name} missing 'name' field")
            return None

        verdict_str = rule_def.get("verdict", "block")
        if verdict_str not in ("block", "gray", "allow"):
            logger.warning(f"YAML rule {name}: invalid verdict '{verdict_str}'")
            return None

        tools = set(rule_def.get("tools", []))
        condition = rule_def.get("condition", {})
        message = rule_def.get("message", f"Rule '{name}' triggered")

        def yaml_rule(tool: str, args: dict, _name=name, _tools=tools,
                      _condition=condition, _verdict=verdict_str,
                      _message=message) -> Decision | None:
            if _tools and tool not in _tools:
                return None

            if _condition and not _evaluate_condition(_condition, args):
                return None

            if _verdict == "block":
                return Decision.block(reason=_message, rule_name=_name)
            elif _verdict == "gray":
                return Decision.gray(reason=_message, rule_name=_name)
            else:
                return Decision.allow()

        yaml_rule.__name__ = f"yaml_rule_{name}"
        return yaml_rule

    except Exception as e:
        logger.error(f"Failed to compile YAML rule {yaml_file.name}: {e}")
        return None


def _evaluate_condition(condition: dict, args: dict) -> bool:
    """Evaluate a YAML condition against tool arguments."""
    if not condition:
        return True

    field = condition.get("field", "")
    operator = condition.get("operator", "")
    value = condition.get("value")

    field_val = args.get(field)

    if operator == "count_gt":
        return isinstance(field_val, list) and len(field_val) > value
    elif operator == "count_gte":
        return isinstance(field_val, list) and len(field_val) >= value
    elif operator == "equals":
        return field_val == value
    elif operator == "contains":
        return value in str(field_val or "")
    elif operator == "not_contains":
        return value not in str(field_val or "")
    elif operator == "exists":
        return field_val is not None
    elif operator == "regex_match":
        return bool(re.search(str(value), str(field_val or ""), re.IGNORECASE))
    else:
        logger.warning(f"Unknown condition operator: {operator}")
        return False
