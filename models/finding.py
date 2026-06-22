from dataclasses import dataclass
from typing import Optional


@dataclass
class Finding:
    """
    Fundamental radiological finding object.
    """

    name: str

    organ: Optional[str] = None

    location: Optional[str] = None

    side: Optional[str] = None

    size_mm: Optional[float] = None

    description: Optional[str] = None

    certainty: str = "MODERATE"

    status: str = "ACTIVE"
