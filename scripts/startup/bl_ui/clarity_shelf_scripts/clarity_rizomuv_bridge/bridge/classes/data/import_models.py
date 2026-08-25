"""Data classes representing data imported from RizomUV."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RizomData:
    """Data from the current RizomUV session."""

    objects: list[str]
    uv_maps: list[str]
    file_path: str

    def __str__(self):  # noqa: D105
        return f"Objects: {self.objects}\nUV Maps: {self.uv_maps}\nFile Path: {self.file_path}"

    def __post_init__(self):
        """Transform object names to remove any group information.

        When objects are exported they are prefixed with their parent name like parent/child, this
        removes that prefix so the names match in Blender.

        """
        transformed_names = [name.rsplit("/", 1)[-1] if "/" in name else name for name in self.objects]
        object.__setattr__(self, "objects", transformed_names)
