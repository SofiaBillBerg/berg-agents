"""Custom exception hierarchy for the berg_agents package.

All public functions raise :class:`CodeAgentError` (or a subclass) so
that callers can catch a single exception type.  This also allows the
CLI to catch all exceptions and print a user-friendly message.
"""


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

class CodeAgentError(RuntimeError):
    """Base exception for all berg_agents related errors."""
