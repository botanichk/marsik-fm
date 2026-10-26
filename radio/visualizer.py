"""Совместимость: GlowingWave теперь живёт в пакете radio.viz.

Старый путь radio.visualizer сохранён как тонкий реэкспорт, чтобы
импорты вроде `from radio.visualizer import GlowingWave` продолжали работать.
"""
from .viz.glowing_wave import GlowingWave  # noqa: F401
from .viz.base import Visualizer           # noqa: F401

__all__ = ["GlowingWave", "Visualizer"]
