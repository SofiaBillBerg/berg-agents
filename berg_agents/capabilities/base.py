"""Core capability contract for the OAP-inspired layer.

Defines the ``Capability`` protocol (the public interface every capability
must satisfy) and ``CapabilityBase`` (a convenient ABC that implements the
protocol's ``invoke`` dispatch and validation). ``RiskClass`` provides the
canonical risk levels used to gate high-risk capabilities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel

class RiskClass:
    """Canonical risk levels for capabilities.

    Used to gate invocation: high-risk capabilities require explicit
    approval before execution.
    """

    LOW: ClassVar[str] = "low"
    MEDIUM: ClassVar[str] = "medium"
    HIGH: ClassVar[str] = "high"


@runtime_checkable
class Capability(Protocol):
    """Structural contract every capability must satisfy.

    Attributes:
        id: Stable identifier, e.g. ``"read-file"``.
        intent: Human description of what the capability does.
        input_model: Pydantic model validating the invocation params.
        output_model: Pydantic model describing the invocation result.
        risk_class: One of :data:`RiskClass` values.
    """

    id: str
    intent: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk_class: str

    def invoke(self, params: BaseModel) -> BaseModel:
        """Execute the capability against validated ``params``.

        :param params: Validated invocation parameters.
        :return: The capability result.
        """
        ...


@dataclass
class CapabilityBase(ABC):
    """Base class for capabilities. Subclass and implement ``_execute``.

    Subclasses must set the ``id``, ``intent``, ``input_model`` and
    ``output_model`` class attributes. ``invoke`` validates that ``params``
    is an instance of ``input_model`` before delegating to ``_execute``.

    See :class:`Capability` for the structural contract.
    Note that this is an ABC, so subclasses must implement ``_execute``.

    Attributes:
        id: Stable identifier, e.g. ``"read-file"``.
        intent: Human description of what the capability does.
        input_model: Pydantic model validating the invocation params.
        output_model: Pydantic model describing the invocation result.
        risk_class: One of :data:`RiskClass` values.
    """

    id: ClassVar[str]
    intent: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]
    risk_class: ClassVar[str] = RiskClass.LOW

    def invoke(self, params: BaseModel) -> BaseModel:
        """Validate ``params`` and delegate to ``_execute``.

        :param params: The invocation parameters, an instance of ``input_model``.
        :return: The capability result, an instance of ``output_model``.
        :raises TypeError: If ``params`` is not an instance of ``input_model``.
        """
        if not isinstance(params, self.input_model):
            raise TypeError(f"expected {self.input_model.__name__}")
        return self._execute(params)

    @abstractmethod
    def _execute(self, params: BaseModel) -> BaseModel:
        """Implement the capability's actual behavior.

        :param params: Validated invocation parameters.

        :return: The capability result.
        """
        ...

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serializable description of the capability.

        Includes the id, intent, risk class and the JSON schemas of the
        input and output models.

        :return: A dict describing the capability.
        """
        return {
            "id": self.id,
            "intent": self.intent,
            "risk_class": self.risk_class,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
        }
