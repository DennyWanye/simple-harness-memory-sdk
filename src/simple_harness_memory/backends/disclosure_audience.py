"""Conservative ordinary-use audience binding, distinct from grant issuance.

Different recipient/audience enum spellings can mean the same scope. A wider
final audience needs its own verified disclosure path; self delivery alone
must never authorize private inputs for that wider audience.
"""
from simple_harness import DisclosureContext

_ORDINARY_AUDIENCES = {
    "user_self": "user_self",
    "household": "household",
    "task_collaborator": "task_collaborators",
}


def ordinary_audience_matches(disclosure: DisclosureContext) -> bool:
    expected = _ORDINARY_AUDIENCES.get(disclosure.recipient.value)
    return expected is not None and disclosure.intended_audience.value == expected
