#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Context base model definition."""

from typing import Generic, TypeVar, cast, overload

T = TypeVar("T")


class ReadWriteAttribute(Generic[T]):
    """Descriptor for context attributes with R/W access."""

    def __set_name__(self, owner, name):
        """..."""
        self.public_name = name
        self.private_name = "_" + name

    @overload
    def __get__(self, instance: None, owner: type[T]) -> "ReadWriteAttribute":
        ...

    @overload
    def __get__(self, instance: T, owner: type[T]) -> T:
        ...

    def __get__(self, instance: T | None, owner: type[T]) -> T | "ReadWriteAttribute":
        """..."""
        relation_data = getattr(instance, "relation_data")
        if relation_data is None:
            return cast(T, "")

        return cast(T, relation_data.get(self.private_name, ""))

    def __set__(self, instance: T, value: type[T]) -> None:
        """..."""
        relation_data = getattr(instance, "relation_data")
        if relation_data is None:
            raise Exception("Unable to update")

        if not value:
            del relation_data[self.private_name]

        relation_data.update({self.private_name: value})


class BetterContext:
    """..."""

    rest_port: int = ReadWriteAttribute[int]()  # pyright: ignore[reportAssignmentType]

    def __init__(self):
        self.relation_data = {"_rest_port": 1234}


a = BetterContext()
print(a.rest_port)
a.rest_port = 4321
print(a.rest_port)
print(a.relation_data)
