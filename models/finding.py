from dataclasses import dataclass
from typing import List, Optional


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

    confirmed_line_id: Optional[str] = None

    status: str = "ACTIVE"

    # La estructura existe a ambos lados del cuerpo (riñón, mama, mano...).
    # Lo propone el extractor con conocimiento anatómico; None = no sabe.
    paired: Optional[bool] = None

    # Largo, ancho y alto en mm cuando se dictan varias dimensiones
    # (size_mm sigue siendo la mayor). Se usa en el paso de volumen.
    dimensions_mm: Optional[List[float]] = None
