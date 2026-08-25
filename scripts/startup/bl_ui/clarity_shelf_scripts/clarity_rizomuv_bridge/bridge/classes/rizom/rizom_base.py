"""Interface defining common functionality between legacy and modern RizomLink classes."""

from abc import ABC, abstractmethod

from ..data.import_models import RizomData


class RizomBase(ABC):
    """Base class interface for RizomUVLink."""

    @abstractmethod
    def get_scene_data(self) -> RizomData:
        """Get the data from the current RizomUV session.

        Returns:
            A dataclass containing the object names and UV map names from the current RizomUV session.

        """
        pass
