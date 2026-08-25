"""Class for representing and working with version data.

The main purpose is converting the string version pulled from Rizom
into an easily comparable object so I can check what features I can use.

"""


class Version:
    """Class for representing and working with version data."""

    def __init__(self, version_string: str):
        string_list = version_string.split(".")
        del string_list[-1]

        self.major = int(string_list[0])
        self.minor = int(string_list[1])
        self.patch = int(string_list[2])

    def meets_minimum_requirement(self, major: int, minor: int, patch: int) -> bool:
        """Check if the version meets the minimum requirement.

        Args:
            major: Major version number.
            minor: Minor version number.
            patch: Patch version number.

        Returns:
            True if the version meets the minimum requirement.

        """
        return (
            self.major >= major
            or (self.major == major and self.minor >= minor)
            or (self.major == major and self.minor == minor and self.patch >= patch)
        )

    def is_below_version(self, major: int, minor: int, patch: int) -> bool:
        """Check if the version is below the specified version.

        Args:
           major: Major version number.
           minor: Minor version number.
           patch: Patch version number.

        Returns:
           True if the version is below the specified version.

        """
        return not self.meets_minimum_requirement(major, minor, patch)
