from dataclasses import dataclass, field

from app.models import User


@dataclass
class Actor:
    """Who is performing an action, plus request metadata for auditing."""

    user: User | None = None
    actor_type: str = "USER"  # USER | AGENT | SYSTEM
    name: str | None = None
    agent_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    roles: list[str] = field(default_factory=list)

    @property
    def id(self) -> str | None:
        if self.user:
            return self.user.id
        return self.agent_id

    @property
    def display_name(self) -> str:
        if self.user:
            return self.user.full_name
        return self.name or "ASTITVA Security Engine"

    @property
    def role_label(self) -> str | None:
        if self.user:
            return ",".join(self.user.role_names)
        return "AGENT" if self.actor_type == "AGENT" else "SYSTEM"


SYSTEM = Actor(actor_type="SYSTEM", name="ASTITVA Security Engine")
