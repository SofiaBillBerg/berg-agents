# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture. The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://gnu.org/licenses/agpl-3.0.html>.

"""API route modules, one concern per file.

Each module exposes a ``register_*(router, *, harness, sessions, providers)``
function that attaches its endpoints to the shared ``APIRouter``. The
injected dependencies are passed explicitly (no hidden closures), so
``create_router`` just composes the modules instead of holding every
endpoint inline (the "one concern per module" rule replaces the single
over-large ``create_router``).
"""
