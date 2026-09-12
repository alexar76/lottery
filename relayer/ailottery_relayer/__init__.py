"""AI-Agent Oracle Lottery — off-chain economy engine + relayer.

The relayer is the lottery's "brain": it drives the on-chain round lifecycle
(open → sell → close/commit → draw/reveal → settle), obtains and *pays for* the
oracle services each draw consumes (Platon randomness, Chronos VDF, LUMEN
reputation), runs the Hub altruistic tithe (funds ONLY its bound lottery) and the
UNI-mode external benefactor ($100/week), and publishes the live economy to the
Alien Monitor and its own HTTP API.

See lottery/docs/README.md (Deployment, Use cases, "How the Hub and its lottery
are connected") and lottery/docs/AUDIT.md.
"""

__version__ = "0.1.0"
