from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PublishStatus(str, Enum):
    PUBLISHED     = "PUBLISHED"
    DRAFT_CREATED = "DRAFT_CREATED"
    FAILED        = "FAILED"
    SKIPPED       = "SKIPPED"


@dataclass
class PublishResult:
    platform:           str
    status:             PublishStatus
    url:                Optional[str] = None
    external_id:        Optional[str] = None
    error_message:      Optional[str] = None
    raw_response_path:  Optional[str] = None

    def ok(self) -> bool:
        return self.status in (PublishStatus.PUBLISHED, PublishStatus.DRAFT_CREATED)

    def to_dict(self) -> dict:
        return {
            "platform":          self.platform,
            "status":            self.status.value,
            "url":               self.url,
            "external_id":       self.external_id,
            "error_message":     self.error_message,
            "raw_response_path": self.raw_response_path,
        }
