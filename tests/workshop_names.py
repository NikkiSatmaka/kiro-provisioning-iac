"""Pure Python mirror of the claim-service name derivation and state-key scheme.

Feature: multi-workshop-provisioning

This module mirrors, in pure Python, the two pieces of workshop-scoped naming
that the Correctness Properties for Pillar 4 (one claim service per workshop)
exercise:

1. The claim-service resource name derivation. In HCL this is
   ``local.name = "credential-claim-${var.workshop_id}"`` in
   ``claim-service/terraform/dynamodb.tf``, from which ``lambda.tf`` derives the
   DynamoDB table name (``local.name``), the Lambda function name
   (``local.name``), the IAM role name (``${local.name}-lambda``), and the inline
   table-access policy name (``${local.name}-table-access``).

2. The workshop-scoped Terraform state-key scheme the mise tasks pass at init
   time: ``workshops/<workshop_id>/<stack>/terraform.tfstate`` for the
   ``subscription`` and ``claim-service`` stacks (mise.toml ``-backend-config``).

A sibling task (5.4) owns ``tests/workshop_state_keys.py`` with its own
``state_key``; to avoid a concurrent write race on one shared helper, this module
defines ``state_key`` independently. The small duplication across two separate
test-helper modules is deliberate and acceptable.

The functions here are the single source of truth the Pillar-4 property tests
compare against, so a drift between this mirror and the HCL/mise derivation would
surface as a failing property rather than silently diverging.
"""

from __future__ import annotations

# The two Terraform stacks that keep per-workshop state in the shared backend.
STACKS: tuple[str, ...] = ("subscription", "claim-service")


def name(workshop_id: str) -> str:
    """The namespaced base name every claim resource derives from.

    Mirrors ``local.name = "credential-claim-${var.workshop_id}"``.
    """
    return f"credential-claim-{workshop_id}"


def table_name(workshop_id: str) -> str:
    """DynamoDB table name — exactly ``local.name`` (dynamodb.tf)."""
    return name(workshop_id)


def lambda_name(workshop_id: str) -> str:
    """Lambda function name — exactly ``local.name`` (lambda.tf)."""
    return name(workshop_id)


def role_name(workshop_id: str) -> str:
    """IAM execution-role name — ``${local.name}-lambda`` (lambda.tf)."""
    return f"{name(workshop_id)}-lambda"


def policy_name(workshop_id: str) -> str:
    """Inline table-access policy name — ``${local.name}-table-access``."""
    return f"{name(workshop_id)}-table-access"


def state_key(workshop_id: str, stack: str) -> str:
    """Workshop-scoped Terraform state key for one stack.

    Mirrors the mise init-time
    ``-backend-config="key=workshops/<id>/<stack>/terraform.tfstate"``.
    """
    return f"workshops/{workshop_id}/{stack}/terraform.tfstate"


def derived_names(workshop_id: str) -> list[str]:
    """All claim resource names derived from ``workshop_id``."""
    return [
        table_name(workshop_id),
        lambda_name(workshop_id),
        role_name(workshop_id),
        policy_name(workshop_id),
    ]


def derived_values(workshop_id: str) -> list[str]:
    """Every derived name plus both state keys for ``workshop_id``.

    This is the full set a distinct second workshop must share no value with.
    """
    return derived_names(workshop_id) + [
        state_key(workshop_id, stack) for stack in STACKS
    ]
