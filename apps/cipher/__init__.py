"""Cipher synthetic prototype.

Cipher is S&A Solutions' owned AEC/EPC project-controls and accounting core,
operated through explicit human approvals.  This package is the bounded
*synthetic* first slice described in the Cipher planning package (v1.1,
solo-first): one owner, one USD entity, one synthetic project, shadow finance
and simulated payments.

Design rules enforced throughout the package:

* exact decimal money, never binary floats;
* every consequential action binds a server-generated approval manifest and a
  changed manifest invalidates the approval;
* posted journals are immutable and corrections append reversals;
* period locks apply to every posting path;
* a payment can only leave through a committed outbox row, a timeout after
  submission is *outcome unknown* until reconciled, and replayed commands or
  provider events never create a second transfer;
* Ricky proposes, deterministic services decide.

Nothing here connects to production systems, real payment rails or live
records.  Standard library only.
"""

__version__ = "0.2.0"
__all__ = ["__version__"]
