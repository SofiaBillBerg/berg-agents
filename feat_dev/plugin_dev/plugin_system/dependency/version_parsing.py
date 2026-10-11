#  <one line to give the program's name and a brief idea of what it does.>
#
#  Copyright (c) 2026.
#          Copyright (C) <year>  <name of author>
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

#  <one line to give the program's name and a brief idea of what it does.>
#
#
#          This program is free software: you can redistribute it and/or modify
#          it under the terms of the GNU Affero General Public License as
#          published by the Free Software Foundation, either version 3 of the
#          License, or (at your option) any later version.
#
#          This program is distributed in the hope that it will be useful,
#          but WITHOUT ANY WARRANTY; without even the implied warranty of
#          MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#          GNU Affero General Public License for more details.
#
#          You should have received a copy of the GNU Affero General Public License
#          along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

# Version Parsing

import re
from dataclasses import dataclass


@dataclass
class Version:
    """Semantic version."""

    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    build: str | None = None

    @classmethod
    def parse(cls, version_string: str) -> "Version":
        """Parse version string."""
        pattern = r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z-.]+))?(?:\+([0-9A-Za-z-.]+))?$"
        match = re.match(pattern, version_string)

        if not match:
            raise ValueError(f"Invalid version: {version_string}")

        major, minor, patch, prerelease, build = match.groups()

        return cls(
            major=int(major),
            minor=int(minor),
            patch=int(patch),
            prerelease=prerelease,
            build=build,
        )

    def __str__(self) -> str:
        v = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            v += f"-{self.prerelease}"
        if self.build:
            v += f"+{self.build}"
        return v

    def __lt__(self, other: "Version") -> bool:
        """Compare versions."""
        if self.major != other.major:
            return self.major < other.major
        if self.minor != other.minor:
            return self.minor < other.minor
        if self.patch != other.patch:
            return self.patch < other.patch

        # Prerelease versions have lower precedence
        if self.prerelease and not other.prerelease:
            return True
        if not self.prerelease and other.prerelease:
            return False
        if self.prerelease and other.prerelease:
            return self.prerelease < other.prerelease

        return False

    def satisfies(self, constraint: str) -> bool:
        """Check if version satisfies constraint."""
        return VersionConstraint.parse(constraint).matches(self)


class VersionConstraint:
    """Version constraint matcher."""

    def __init__(self, constraint_str: str) -> None:
        self.constraint_str = constraint_str
        self.matchers = self._parse(constraint_str)

    @classmethod
    def parse(cls, constraint_str: str) -> "VersionConstraint":
        """Parse constraint string."""
        return cls(constraint_str)

    def _parse(self, constraint: str):
        """Parse constraint into matcher functions."""
        constraint = constraint.strip()

        # Wildcard
        if constraint == "*":
            return [lambda v: True]

        # Caret (^1.2.3 → >=1.2.3 <2.0.0)
        if constraint.startswith("^"):
            base = Version.parse(constraint[1:])
            return [lambda v: v >= base, lambda v: v.major == base.major]

        # Tilde (~1.2.3 → >=1.2.3 <1.3.0)
        if constraint.startswith("~"):
            base = Version.parse(constraint[1:])
            return [
                lambda v: v >= base,
                lambda v: v.major == base.major and v.minor == base.minor]

        # Range (>=1.0.0 <2.0.0)
        if " " in constraint:
            parts = constraint.split()
            matchers = []
            for part in parts:
                matchers.extend(self._parse(part))
            return matchers

        # Comparison operators
        for op in [">=", "<=", ">", "<", "="]:
            if constraint.startswith(op):
                version = Version.parse(constraint[len(op):])
                if op == ">=":
                    return [lambda v: v >= version]
                elif op == "<=":
                    return [lambda v: v <= version]
                elif op == ">":
                    return [lambda v: v > version]
                elif op == "<":
                    return [lambda v: v < version]
                elif op == "=":
                    return [lambda v: v == version]

        # Exact version
        version = Version.parse(constraint)
        return [lambda v: v == version]

    def matches(self, version: Version) -> bool:
        """Check if version matches constraint."""
        return all(matcher(version) for matcher in self.matchers)
