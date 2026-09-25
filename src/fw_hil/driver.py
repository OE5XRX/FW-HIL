# SPDX-License-Identifier: GPL-3.0-or-later
"""Bench-driver interface. Backends implement the four HW primitives."""

from abc import ABC, abstractmethod


class BenchDriver(ABC):
    @abstractmethod
    def flash(self, image_path: str) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def mass_erase(self) -> None: ...

    @abstractmethod
    def power_cycle(self) -> None: ...
