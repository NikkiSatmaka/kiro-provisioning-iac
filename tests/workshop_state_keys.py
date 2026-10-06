"""Pure Python mirror of the workshop-scoped state-key scheme.

Feature: multi-workshop-provisioning

Pillar 3 removes the hard-coded ``key`` from both ``backend.hcl`` files and
supplies a per-workshop state path at init time instead. The mise tasks derive
that path from ``WORKSHOP_ID`` as::

    workshops/${WID}/subscription/terraform.tfstate
    workshops/${WID}/claim-service/terraform.tfstate

(see ``mise.toml`` ``SUB_KEY`` and the ``-backend-config="key=..."`` lines, and
``backend/terraform/outputs.tf`` which documents the same layout). The two
stacks' keys differ only in the stack segment and share the same
``<workshop_id>`` (R5.2, R5.3, R7.4).

This module is a *pure* re-implementation of that single derivation so the
Property 9 test can assert the scheme offline over many generated workshop ids,
with no ``tofu`` process and no AWS. Keep it a faithful mirror of the shell
expression ``"workshops/${WID}/<stack>/terraform.tfstate"``: if that scheme ever
changes, this mirror changes with it.

Defined in its own module (rather than a shared names mirror) so concurrent
sibling test tasks that add their own derivation mirrors do not collide on this
file.
"""

from __future__ import annotations

# The two stacks that get a per-workshop state key, matching the segments the
# mise tasks use in ``-backend-config="key=workshops/${WID}/<stack>/..."``.
SUBSCRIPTION_STACK = "subscription"
CLAIM_SERVICE_STACK = "claim-service"

STATE_FILENAME = "terraform.tfstate"


def state_key(workshop_id: str, stack: str) -> str:
    """The S3 state key for a ``(workshop_id, stack)`` pair.

    Mirrors the shell derivation
    ``"workshops/${WID}/<stack>/terraform.tfstate"`` exactly: a fixed
    ``workshops/`` prefix, the workshop id, the stack segment, and the
    ``terraform.tfstate`` filename, joined by ``/``.
    """
    return f"workshops/{workshop_id}/{stack}/{STATE_FILENAME}"
