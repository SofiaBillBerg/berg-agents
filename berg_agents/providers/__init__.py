"""Provider layer - model resolution.

The only public surface is :func:`resolve_model_instance`, which reads
``config/bergagents.jsonc`` and returns a fully-configured
:class:`~pydantic_ai.models.openai.OpenAIChatModel`. The old ``LLMProvider``
protocol / ``ProviderBase`` ABC were removed as dead code (nobody subclasses
or instantiates them).
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

from __future__ import annotations

from .models import resolve_model_instance, resolve_model_string


__all__ = ["resolve_model_instance", "resolve_model_string"]
