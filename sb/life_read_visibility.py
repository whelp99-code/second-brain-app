"""Policy-authorized event snapshot for read requests."""

from datetime import datetime
from pathlib import Path

from sb.config import Config
from sb.life_actor import LifeActor
from sb.life_config import policies
from sb.life_contracts import LifeEventV1
from sb.store.life import read_life_store


def visible_events(
    config: Config, root: Path, actor: LifeActor, now: datetime
) -> tuple[tuple[LifeEventV1, ...], bool]:
    configured = policies(config)
    active = tuple(s for s in actor.source_ids if s in configured and configured[s].enabled)
    if not active:
        return (), True
    with read_life_store(root) as store:
        candidates = store.events(scopes=actor.scopes, now=now, limit=10000, source_ids=active)
    events = tuple(
        e
        for e in candidates
        if e.scopes == configured[e.source_id].scopes
        and e.sensitivity == configured[e.source_id].sensitivity
        and e.external_processing == configured[e.source_id].external_processing
        and e.policy_revision == configured[e.source_id].policy_revision
    )
    return events, len(candidates) < 10000
