# Berg Agents is a sophisticated multi-agent system built with a modular, extensible architecture.
# The system follows a harness-based execution model with multiple specialized agents working together.
#
# Copyright (C) 2026 Sofia Billger Bergström <sofia.billger.bergstrom@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
#
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

"""Provider layer - model resolution.

The only public surface is :func:`resolve_model_instance`, which reads
``.berg-agents/bergagents.jsonc`` and returns a fully-configured
:class:`~pydantic_ai.models.openai.OpenAIChatModel`. The old ``LLMProvider``
protocol / ``ProviderBase`` ABC were removed as dead code (nobody subclasses
or instantiates them).
"""

from __future__ import annotations

from .models import resolve_model_instance, resolve_model_string

__all__ = ["resolve_model_instance", "resolve_model_string"]
