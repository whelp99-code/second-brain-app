"""Policy-filtered workflow event visibility."""

from datetime import datetime

from sb.config import Config
from sb.life_config import policies, settings
from sb.life_contracts import LifeEventV1, LifeInputError
from sb.store.life import LifeStore


def visible(
    config: Config,
    store: LifeStore,
    *,
    source_ids: tuple[str, ...],
    scopes: tuple[str, ...],
    now: datetime,
    client: bool = False,
) -> tuple[LifeEventV1, ...]:
    configured = policies(config)
    selected = tuple(s for s in source_ids if s in configured and configured[s].enabled)
    if not selected:
        return ()
    candidates = store.events(scopes=scopes, now=now, source_ids=selected, limit=10000)
    if len(candidates) >= 10000:
        raise LifeInputError("LIFE_WORKSET_TOO_LARGE")
    opts = settings(config)
    return tuple(
        e
        for e in candidates
        if (
            e.scopes == configured[e.source_id].scopes
            and e.sensitivity == configured[e.source_id].sensitivity
            and e.external_processing == configured[e.source_id].external_processing
            and e.policy_revision == configured[e.source_id].policy_revision
            and (not client or e.sensitivity in opts.view_sensitivities)
        )
    )
