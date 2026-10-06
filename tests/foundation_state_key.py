"""Pure Python mirror of the Foundation IdC state-key constant.

Feature: foundation-idc-service

Because the IdC instance is a single shared foundation resource — NOT
workshop-scoped — the foundation tasks supply a fixed, prefix-free init-time
state key. Each ``foundation-plan`` / ``foundation-apply`` / ``foundation-destroy``
task runs::

    tofu init -reconfigure -input=false \\
      -backend-config=backend.hcl \\
      -backend-config="key=foundation/terraform.tfstate"

(see ``mise.toml`` and ``foundation/terraform/backend.hcl.example``). That key is
the bare ``foundation/terraform.tfstate`` — it carries NO ``workshops/<id>/``
prefix, which is the one difference from the subscription/claim-service keys that
are workshop-namespaced (``workshops/<id>/<stack>/terraform.tfstate``) (R4.3,
R4.4, R6.4).

This module is a *pure* re-implementation of that single constant so the
Property 5 test can assert the key offline, with no ``tofu`` process and no AWS.
Keep it a faithful mirror of the ``-backend-config="key=..."`` literal the
foundation tasks use: if that key ever changes, this mirror changes with it.

Defined in its own module (rather than a shared mirror) so concurrent sibling
test tasks that add their own derivation mirrors do not collide on this file. It
is importable via the shared conftest ``sys.path`` shim (``tests/`` is on the
path).
"""

from __future__ import annotations

#: The fixed, prefix-free init-time state key the foundation tasks supply to
#: ``tofu init`` via ``-backend-config="key=foundation/terraform.tfstate"``
#: (R4.3, R6.4). Mirrors the literal in ``mise.toml``.
FOUNDATION_STATE_KEY = "foundation/terraform.tfstate"

#: The workshop-scoping prefix the workshop-namespaced keys begin with. The
#: foundation key never starts with ``workshops/<id>/`` (R4.4); this segment is
#: exposed so the sibling property test can assert the distinction without
#: re-hardcoding the literal.
WORKSHOPS_PREFIX = "workshops/"


def foundation_state_key() -> str:
    """Return the fixed foundation state key.

    Mirrors the ``-backend-config="key=foundation/terraform.tfstate"`` literal
    the foundation tasks supply at ``tofu init`` time: the bare
    ``foundation/terraform.tfstate``, with no ``workshops/<id>/`` prefix.
    """
    return FOUNDATION_STATE_KEY
